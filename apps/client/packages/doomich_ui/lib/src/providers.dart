import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:doomich_core/doomich_core.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path_provider/path_provider.dart';

import 'settings.dart';

/// Токены — в защищённом хранилище ОС (Android Keystore, Windows Credential Manager, libsecret).
class SecureTokenStore implements TokenStore {
  SecureTokenStore([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _access = 'doomich_access';
  static const _refresh = 'doomich_refresh';

  @override
  Future<String?> readAccess() => _storage.read(key: _access);
  @override
  Future<String?> readRefresh() => _storage.read(key: _refresh);
  @override
  Future<void> save(String access, String refresh) async {
    await _storage.write(key: _access, value: access);
    await _storage.write(key: _refresh, value: refresh);
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: _access);
    await _storage.delete(key: _refresh);
  }
}

/// Запасное хранилище токенов для Linux без Secret Service (нет «связки ключей»):
/// файл в каталоге приложения с правами 0600 — как это делают CLI-инструменты.
class FileTokenStore implements TokenStore {
  FileTokenStore(this.file);

  final File file;

  Future<Map<String, dynamic>> _read() async {
    if (!await file.exists()) return {};
    try {
      return jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    } on FormatException {
      return {};
    }
  }

  @override
  Future<String?> readAccess() async => (await _read())['access'] as String?;
  @override
  Future<String?> readRefresh() async => (await _read())['refresh'] as String?;

  @override
  Future<void> save(String access, String refresh) async {
    await file.parent.create(recursive: true);
    await file.writeAsString(jsonEncode({'access': access, 'refresh': refresh}), flush: true);
    if (Platform.isLinux || Platform.isMacOS) await Process.run('chmod', ['600', file.path]);
  }

  @override
  Future<void> clear() async {
    if (await file.exists()) await file.delete();
  }
}

/// Есть ли в сессии D-Bus служба секретов (gnome-keyring, KWallet и т. п.).
Future<bool> linuxSecretServiceAvailable() async {
  Future<bool> call(String method) async {
    try {
      final result = await Process.run('gdbus', [
        'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
        '--method', 'org.freedesktop.DBus.$method',
      ]).timeout(const Duration(seconds: 3));
      return result.exitCode == 0 && (result.stdout as String).contains('org.freedesktop.secrets');
    } catch (_) {
      return false;
    }
  }

  return await call('ListNames') || await call('ListActivatableNames');
}

/// Выбрать хранилище токенов для платформы (вызывается до запуска приложения).
Future<TokenStore> createTokenStore() async {
  if (Platform.isLinux && !await linuxSecretServiceAvailable()) {
    final dir = await getApplicationSupportDirectory();
    return FileTokenStore(File('${dir.path}/session.json'));
  }
  return SecureTokenStore();
}

/// Подменяется в runDoomich результатом [createTokenStore].
final tokenStoreProvider = Provider<TokenStore>((ref) => SecureTokenStore());

final apiClientProvider = Provider<ApiClient>((ref) {
  final base = ref.watch(settingsProvider.select((s) => s.apiBase));
  return ApiClient(
    baseUrl: Uri.parse(base),
    tokens: ref.watch(tokenStoreProvider),
    onSessionExpired: () => ref.read(sessionProvider.notifier).expired(),
  );
});

final authRepositoryProvider = Provider((ref) => AuthRepository(ref.watch(apiClientProvider)));
final chatRepositoryProvider = Provider((ref) => ChatRepository(ref.watch(apiClientProvider)));
final documentsRepositoryProvider = Provider((ref) => DocumentsRepository(ref.watch(apiClientProvider)));
final lecturesRepositoryProvider = Provider((ref) => LecturesRepository(ref.watch(apiClientProvider)));
final navigationRepositoryProvider = Provider((ref) => NavigationRepository(ref.watch(apiClientProvider)));

/// Каталог для офлайн-кэша (расписание).
final cacheDirectoryProvider = FutureProvider<Directory>((ref) async {
  final base = await getApplicationSupportDirectory();
  return Directory('${base.path}/cache');
});

final scheduleRepositoryProvider = FutureProvider<ScheduleRepository>((ref) async {
  final dir = await ref.watch(cacheDirectoryProvider.future);
  return ScheduleRepository(ref.watch(apiClientProvider), cache: JsonCache(dir));
});

/// Истёк ли JWT (без проверки подписи — только чтобы обновить токен заранее).
bool isJwtExpired(String token, {Duration leeway = const Duration(seconds: 30)}) {
  final parts = token.split('.');
  if (parts.length != 3) return true;
  try {
    final payload = jsonDecode(utf8.decode(base64Url.decode(base64Url.normalize(parts[1])))) as Map<String, dynamic>;
    final exp = DateTime.fromMillisecondsSinceEpoch((payload['exp'] as int) * 1000);
    return DateTime.now().add(leeway).isAfter(exp);
  } catch (_) {
    return true;
  }
}

/// Действующий access-токен (для WebSocket, где перехватчик dio не работает).
Future<String?> freshAccessToken(ApiClient api) async {
  final token = await api.tokens.readAccess();
  if (token != null && !isJwtExpired(token)) return token;
  return await api.refreshSession() ? api.tokens.readAccess() : null;
}

// ---------------------------------------------------------------------------- сессия
class SessionController extends AsyncNotifier<Me?> {
  @override
  Future<Me?> build() async {
    final tokens = ref.read(tokenStoreProvider);
    if (await tokens.readRefresh() == null) return null;
    try {
      return await ref.read(authRepositoryProvider).me();
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        await tokens.clear();
        return null;
      }
      rethrow;
    }
  }

  /// После регистрации, входа или восстановления (код восстановления показывает экран онбординга).
  void signedIn(Me me) => state = AsyncData(me);

  Future<void> login(String login, String password) async {
    final result = await ref.read(authRepositoryProvider).login(login, password);
    state = AsyncData(result.user);
  }

  Future<void> refreshMe() async {
    final me = await ref.read(authRepositoryProvider).me();
    if (ref.mounted) state = AsyncData(me);
  }

  Future<void> updateMe({String? locale, String? groupId, bool clearGroup = false, int? historyDays}) async {
    final me = await ref
        .read(authRepositoryProvider)
        .updateMe(locale: locale, groupId: groupId, clearGroup: clearGroup, historyDays: historyDays);
    if (ref.mounted) state = AsyncData(me);
  }

  Future<void> logout() async {
    await ref.read(authRepositoryProvider).logout();
    _reset();
  }

  Future<void> deleteAccount(String password) async {
    await ref.read(authRepositoryProvider).deleteAccount(password);
    _reset();
  }

  void expired() {
    if (state.value != null) _reset();
  }

  void _reset() {
    ref.invalidate(chatListProvider);
    ref.invalidate(documentsProvider);
    ref.invalidate(lecturesProvider);
    state = const AsyncData(null);
  }
}

final sessionProvider = AsyncNotifierProvider<SessionController, Me?>(SessionController.new);

// ---------------------------------------------------------------------------- чаты
class ChatListController extends AsyncNotifier<List<ChatSummary>> {
  @override
  Future<List<ChatSummary>> build() => ref.read(chatRepositoryProvider).list();

  Future<ChatSummary> create({List<String> documentIds = const [], String? title}) async {
    final chat = await ref.read(chatRepositoryProvider).create(documentIds: documentIds, title: title);
    state = AsyncData([chat, ...?state.value]);
    return chat;
  }

  Future<void> rename(String id, String title) async {
    final updated = await ref.read(chatRepositoryProvider).rename(id, title);
    state = AsyncData([for (final c in state.value ?? <ChatSummary>[]) c.id == id ? updated : c]);
  }

  Future<void> remove(String id) async {
    await ref.read(chatRepositoryProvider).remove(id);
    state = AsyncData([for (final c in state.value ?? <ChatSummary>[]) if (c.id != id) c]);
  }

  Future<void> refresh() async {
    state = AsyncData(await ref.read(chatRepositoryProvider).list());
  }
}

final chatListProvider = AsyncNotifierProvider<ChatListController, List<ChatSummary>>(ChatListController.new);

// ---------------------------------------------------------------------------- документы
class DocumentsController extends AsyncNotifier<List<DocumentInfo>> {
  Timer? _poll;

  @override
  Future<List<DocumentInfo>> build() async {
    ref.onDispose(() => _poll?.cancel());
    final docs = await ref.read(documentsRepositoryProvider).list();
    _schedulePoll(docs);
    return docs;
  }

  void _schedulePoll(List<DocumentInfo> docs) {
    _poll?.cancel();
    if (docs.any((d) => d.isBusy)) {
      _poll = Timer(const Duration(seconds: 3), () async {
        if (!ref.mounted) return;
        final fresh = await ref.read(documentsRepositoryProvider).list();
        if (!ref.mounted) return;
        state = AsyncData(fresh);
        _schedulePoll(fresh);
      });
    }
  }

  Future<DocumentInfo> upload(String filename, List<int> bytes) async {
    final doc = await ref.read(documentsRepositoryProvider).upload(filename, bytes);
    final docs = [doc, ...?state.value];
    state = AsyncData(docs);
    _schedulePoll(docs);
    return doc;
  }

  Future<void> remove(String id) async {
    await ref.read(documentsRepositoryProvider).remove(id);
    state = AsyncData([for (final d in state.value ?? <DocumentInfo>[]) if (d.id != id) d]);
  }
}

final documentsProvider = AsyncNotifierProvider<DocumentsController, List<DocumentInfo>>(DocumentsController.new);

// ---------------------------------------------------------------------------- конспекты
class LecturesController extends AsyncNotifier<List<Lecture>> {
  Timer? _poll;

  @override
  Future<List<Lecture>> build() async {
    ref.onDispose(() => _poll?.cancel());
    final items = await ref.read(lecturesRepositoryProvider).list();
    _schedulePoll(items);
    return items;
  }

  void _schedulePoll(List<Lecture> items) {
    _poll?.cancel();
    if (items.any((l) => !l.isReady && !l.isFailed)) {
      _poll = Timer(const Duration(seconds: 5), () async {
        if (!ref.mounted) return;
        final fresh = await ref.read(lecturesRepositoryProvider).list();
        if (!ref.mounted) return;
        state = AsyncData(fresh);
        _schedulePoll(fresh);
      });
    }
  }

  Future<void> upload({
    required String filename,
    required List<int> bytes,
    required String title,
    required String template,
    required bool consent,
  }) async {
    final lecture = await ref
        .read(lecturesRepositoryProvider)
        .upload(filename: filename, bytes: bytes, title: title, template: template, teacherConsent: consent);
    final items = [lecture, ...?state.value];
    state = AsyncData(items);
    _schedulePoll(items);
  }

  Future<void> remove(String id) async {
    await ref.read(lecturesRepositoryProvider).remove(id);
    state = AsyncData([for (final l in state.value ?? <Lecture>[]) if (l.id != id) l]);
  }
}

final lecturesProvider = AsyncNotifierProvider<LecturesController, List<Lecture>>(LecturesController.new);
