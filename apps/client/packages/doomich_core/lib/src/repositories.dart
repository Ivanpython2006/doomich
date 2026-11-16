import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'api_client.dart';
import 'models.dart';
import 'sse.dart';

// ---------------------------------------------------------------------------- аккаунт
class AuthRepository {
  AuthRepository(this.api);

  final ApiClient api;

  Future<List<String>> pseudonyms(String locale) async {
    final data = await api.get<Map<String, dynamic>>('/v1/auth/pseudonyms', query: {'locale': locale}, auth: false);
    return (data['suggestions'] as List).cast<String>();
  }

  Future<InviteInfo> checkInvite(String code) async =>
      InviteInfo.fromJson(await api.post('/v1/auth/invite/check', body: {'code': code}, auth: false));

  Future<LoginCheck> checkLogin(String login) async =>
      LoginCheck.fromJson(await api.post('/v1/auth/check-login', body: {'login': login}, auth: false));

  Future<AuthResult> register({required String inviteCode, required String login, required String password, String locale = 'ru'}) =>
      _authenticate('/v1/auth/register', {'invite_code': inviteCode, 'login': login, 'password': password, 'locale': locale});

  Future<AuthResult> login(String login, String password) =>
      _authenticate('/v1/auth/login', {'login': login, 'password': password});

  Future<AuthResult> recover({required String login, required String recoveryCode, required String newPassword}) =>
      _authenticate('/v1/auth/recover', {'login': login, 'recovery_code': recoveryCode, 'new_password': newPassword});

  Future<AuthResult> _authenticate(String path, Map<String, dynamic> body) async {
    final result = AuthResult.fromJson(await api.post(path, body: body, auth: false));
    await api.tokens.save(result.accessToken, result.refreshToken);
    return result;
  }

  Future<void> logout() async {
    final refresh = await api.tokens.readRefresh();
    if (refresh != null) {
      try {
        await api.post<dynamic>('/v1/auth/logout', body: {'refresh_token': refresh}, auth: false);
      } on ApiException {
        // выходим локально в любом случае
      }
    }
    await api.tokens.clear();
  }

  Future<Me> me() async => Me.fromJson(await api.get('/v1/me'));

  Future<Me> updateMe({String? locale, String? groupId, bool clearGroup = false, int? historyDays}) async => Me.fromJson(
    await api.patch('/v1/me', body: {
      'locale': ?locale,
      'group_id': ?groupId,
      if (clearGroup) 'clear_group': true,
      'history_days': ?historyDays,
    }),
  );

  Future<void> changePassword(String oldPassword, String newPassword) =>
      api.post<dynamic>('/v1/auth/password', body: {'old_password': oldPassword, 'new_password': newPassword});

  Future<void> deleteAccount(String password) async {
    await api.delete<dynamic>('/v1/account', body: {'password': password});
    await api.tokens.clear();
  }

  Future<void> deleteMyData() => api.delete<dynamic>('/v1/me/data');

  Future<List<StudyGroup>> groups(String query) async =>
      (await api.get<List<dynamic>>('/v1/groups', query: {'q': query}))
          .map((g) => StudyGroup.fromJson(g as Map<String, dynamic>))
          .toList();

  // Вход на ПК по QR (R2.0): ПК начинает, телефон подтверждает
  Future<({String challengeId, String secret})> qrStart() async {
    final data = await api.post<Map<String, dynamic>>('/v1/auth/qr/start', auth: false);
    return (challengeId: data['challenge_id'] as String, secret: data['secret'] as String);
  }

  Future<void> qrApprove(String secret) => api.post<dynamic>('/v1/auth/qr/approve', body: {'secret': secret});

  Future<AuthResult?> qrPoll(String challengeId, String secret) async {
    final data = await api.post<dynamic>('/v1/auth/qr/poll', body: {'challenge_id': challengeId, 'secret': secret}, auth: false);
    if (data == null) return null;
    final result = AuthResult.fromJson(data as Map<String, dynamic>);
    await api.tokens.save(result.accessToken, result.refreshToken);
    return result;
  }
}

// ---------------------------------------------------------------------------- чат
sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

class ChatDelta extends ChatStreamEvent {
  const ChatDelta(this.text);
  final String text;
}

class ChatTool extends ChatStreamEvent {
  const ChatTool(this.name);
  final String name;
}

class ChatCitations extends ChatStreamEvent {
  const ChatCitations(this.citations);
  final List<Citation> citations;
}

class ChatDone extends ChatStreamEvent {
  const ChatDone({required this.text, this.messageId, this.citations = const []});
  final String text;
  final String? messageId;
  final List<Citation> citations;
}

class ChatError extends ChatStreamEvent {
  const ChatError(this.message);
  final String message;
}

ChatStreamEvent? chatEventFromSse(SseEvent e) {
  List<Citation> cites(Object? raw) =>
      (raw as List? ?? const []).map((c) => Citation.fromJson(c as Map<String, dynamic>)).toList();
  return switch (e.event) {
    'delta' => ChatDelta(e.data['text'] as String? ?? ''),
    'tool' => ChatTool(e.data['name'] as String? ?? ''),
    'citations' => ChatCitations(cites(e.data['citations'])),
    'done' => ChatDone(
      text: e.data['text'] as String? ?? '',
      messageId: e.data['message_id'] as String?,
      citations: cites(e.data['citations']),
    ),
    'error' => ChatError(e.data['message'] as String? ?? 'Ошибка'),
    _ => null,
  };
}

class ChatRepository {
  ChatRepository(this.api);

  final ApiClient api;

  Future<List<ChatSummary>> list() async =>
      (await api.get<List<dynamic>>('/v1/chats')).map((c) => ChatSummary.fromJson(c as Map<String, dynamic>)).toList();

  Future<ChatSummary> create({String? title, List<String> documentIds = const []}) async => ChatSummary.fromJson(
    await api.post('/v1/chats', body: {'title': ?title, 'document_ids': documentIds}),
  );

  Future<ChatSummary> rename(String chatId, String title) async =>
      ChatSummary.fromJson(await api.patch('/v1/chats/$chatId', body: {'title': title}));

  Future<void> remove(String chatId) => api.delete<dynamic>('/v1/chats/$chatId');

  Future<List<ChatMessage>> messages(String chatId) async => (await api.get<List<dynamic>>('/v1/chats/$chatId/messages'))
      .map((m) => ChatMessage.fromJson(m as Map<String, dynamic>))
      .toList();

  Stream<ChatStreamEvent> send(String chatId, String text, {CancelToken? cancel}) => api
      .postSse('/v1/chats/$chatId/messages', {'text': text, 'mode': 'text'}, cancel: cancel)
      .map(chatEventFromSse)
      .where((e) => e != null)
      .cast<ChatStreamEvent>();

  /// Ответ без сохранения на сервере: история передаётся с устройства.
  Stream<ChatStreamEvent> incognito(
    String text, {
    List<ChatMessage> history = const [],
    List<String> documentIds = const [],
    CancelToken? cancel,
  }) => api
      .postSse('/v1/chat/incognito', {
        'text': text,
        'history': history.map((m) => m.toHistory()).toList(),
        'document_ids': documentIds,
      }, cancel: cancel)
      .map(chatEventFromSse)
      .where((e) => e != null)
      .cast<ChatStreamEvent>();

  Future<void> feedback({String? messageId, required int rating, String? comment, bool includeDialog = false}) =>
      api.post<dynamic>('/v1/feedback', body: {
        'message_id': ?messageId,
        'rating': rating,
        'comment': ?comment,
        'include_dialog': includeDialog,
      });
}

// ---------------------------------------------------------------------------- кэш
/// Простой кэш JSON в файлах (офлайн-расписание и т. п.). Каталог задаёт приложение.
class JsonCache {
  JsonCache(this.directory);

  final Directory directory;

  File _file(String key) => File('${directory.path}/${key.replaceAll(RegExp(r'[^\w.-]'), '_')}.json');

  Future<void> put(String key, Object value) async {
    await directory.create(recursive: true);
    final file = _file(key);
    final tmp = File('${file.path}.tmp');
    await tmp.writeAsString(jsonEncode({'saved_at': DateTime.now().toIso8601String(), 'value': value}));
    await tmp.rename(file.path);
  }

  Future<({Object? value, DateTime savedAt})?> get(String key) async {
    final file = _file(key);
    if (!await file.exists()) return null;
    try {
      final data = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
      return (value: data['value'], savedAt: DateTime.parse(data['saved_at'] as String));
    } on FormatException {
      return null;
    }
  }

  Future<void> clear() async {
    if (await directory.exists()) await directory.delete(recursive: true);
  }
}

// ---------------------------------------------------------------------------- расписание
class ScheduleResult {
  const ScheduleResult(this.events, {this.offline = false, this.savedAt});

  final List<ScheduleEvent> events;
  final bool offline;
  final DateTime? savedAt;
}

class ScheduleRepository {
  ScheduleRepository(this.api, {this.cache});

  final ApiClient api;
  final JsonCache? cache;

  static String _d(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  /// Расписание за период. Без сети — последняя сохранённая копия с отметкой времени.
  Future<ScheduleResult> events(DateTime from, DateTime to, {String? groupId, String? teacher}) async {
    final key = 'schedule_${groupId ?? 'my'}_${teacher ?? ''}_${_d(from)}_${_d(to)}';
    try {
      final raw = await api.get<List<dynamic>>('/v1/schedule', query: {
        'from': _d(from),
        'to': _d(to),
        'group_id': ?groupId,
        'teacher': ?teacher,
      });
      await cache?.put(key, raw);
      return ScheduleResult(raw.map((e) => ScheduleEvent.fromJson(e as Map<String, dynamic>)).toList());
    } on ApiException catch (e) {
      final cached = e.isNetwork ? await cache?.get(key) : null;
      if (cached == null) rethrow;
      final events = (cached.value as List).map((e) => ScheduleEvent.fromJson(e as Map<String, dynamic>)).toList();
      return ScheduleResult(events, offline: true, savedAt: cached.savedAt);
    }
  }

  Future<List<ScheduleChange>> changes(DateTime since, {String? groupId}) async =>
      (await api.get<List<dynamic>>('/v1/schedule/changes', query: {
        'since': since.toUtc().toIso8601String(),
        'group_id': ?groupId,
      })).map((c) => ScheduleChange.fromJson(c as Map<String, dynamic>)).toList();

  Future<List<String>> teachers(String query) async =>
      (await api.get<List<dynamic>>('/v1/teachers', query: {'q': query})).cast<String>();
}

// ---------------------------------------------------------------------------- документы
class DocumentsRepository {
  DocumentsRepository(this.api);

  final ApiClient api;

  Future<List<DocumentInfo>> list() async =>
      (await api.get<List<dynamic>>('/v1/documents')).map((d) => DocumentInfo.fromJson(d as Map<String, dynamic>)).toList();

  Future<DocumentInfo> get(String id) async => DocumentInfo.fromJson(await api.get('/v1/documents/$id'));

  Future<DocumentInfo> upload(String filename, List<int> bytes, {void Function(int, int)? onProgress}) async =>
      DocumentInfo.fromJson(await api.upload('/v1/documents', filename: filename, bytes: bytes, onProgress: onProgress));

  Future<void> remove(String id) => api.delete<dynamic>('/v1/documents/$id');

  Future<SourceChunk> chunk(String documentId, String chunkId) async =>
      SourceChunk.fromJson(await api.get('/v1/documents/$documentId/chunks/$chunkId'));
}

// ---------------------------------------------------------------------------- конспекты (R1.1)
class LecturesRepository {
  LecturesRepository(this.api);

  final ApiClient api;

  Future<List<Lecture>> list() async =>
      (await api.get<List<dynamic>>('/v1/lectures')).map((l) => Lecture.fromJson(l as Map<String, dynamic>)).toList();

  Future<Lecture> get(String id) async => Lecture.fromJson(await api.get('/v1/lectures/$id'));

  Future<Lecture> upload({
    required String filename,
    required List<int> bytes,
    required String title,
    required bool teacherConsent,
    String template = 'detailed',
    void Function(int, int)? onProgress,
  }) async => Lecture.fromJson(
    await api.upload(
      '/v1/lectures',
      filename: filename,
      bytes: bytes,
      fields: {'title': title, 'template': template, 'teacher_consent': teacherConsent.toString()},
      onProgress: onProgress,
    ),
  );

  Future<Uint8List> export(String id, {String format = 'docx'}) =>
      api.getBytes('/v1/lectures/$id/export', query: {'format': format});

  Future<void> remove(String id) => api.delete<dynamic>('/v1/lectures/$id');
}

// ---------------------------------------------------------------------------- навигация (R2)
class NavigationRepository {
  NavigationRepository(this.api);

  final ApiClient api;

  Future<RouteResult> route({required String origin, required String destination, bool accessible = false}) async =>
      RouteResult.fromJson(
        await api.post('/v1/nav/route', body: {'origin': origin, 'destination': destination, 'accessible': accessible}),
      );

  Future<Map<String, dynamic>> locate({required String campus, String? text, List<Uint8List> frames = const []}) async {
    try {
      final form = FormData.fromMap({
        'campus_slug': campus,
        'text': ?text,
        'images': [for (var i = 0; i < frames.length; i++) MultipartFile.fromBytes(frames[i], filename: 'frame$i.jpg')],
      });
      final resp = await api.dio.post<Map<String, dynamic>>('/v1/nav/locate', data: form);
      return resp.data!;
    } catch (e) {
      throw ApiClient.mapError(e);
    }
  }
}

// ---------------------------------------------------------------------------- озвучка
/// Озвучка готового текста через сервер (кнопка «Озвучить» у ответа).
class SpeechRepository {
  SpeechRepository(this.api);

  final ApiClient api;

  Future<Uint8List> speak(String text, {String? language}) async {
    try {
      final resp = await api.dio.post<List<int>>(
        '/v1/tts',
        data: {'text': text, 'language': ?language},
        options: Options(responseType: ResponseType.bytes),
      );
      return Uint8List.fromList(resp.data!);
    } catch (e) {
      throw ApiClient.mapError(e);
    }
  }
}
