import 'dart:async';

import 'package:doomich_core/doomich_core.dart';
import 'package:doomich_ui/doomich_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

final _api = ApiClient(baseUrl: Uri.parse('http://test'), tokens: MemoryTokenStore());

class FakeAuth extends AuthRepository {
  FakeAuth() : super(_api);

  @override
  Future<InviteInfo> checkInvite(String code) async =>
      InviteInfo(valid: code.startsWith('GOOD'), university: 'Демо-университет', role: 'student', group: 'ИВТ-21-1');

  @override
  Future<LoginCheck> checkLogin(String login) async =>
      const LoginCheck(available: true, valid: true, looksLikeName: false);
}

class FakeChat extends ChatRepository {
  FakeChat() : super(_api);

  final sent = <String>[];

  @override
  Stream<ChatStreamEvent> incognito(String text, {List<ChatMessage> history = const [], List<String> documentIds = const [], CancelToken? cancel}) async* {
    sent.add(text);
    yield const ChatTool('get_schedule');
    yield const ChatDelta('Завтра ');
    yield const ChatDelta('матанализ в 9:00.');
    yield const ChatDone(
      text: 'Завтра матанализ в 9:00. [1]',
      citations: [Citation(n: 1, documentId: 'd1', chunkId: 'c1', title: 'Расписание.pdf', page: 2)],
    );
  }
}

Future<Widget> app(Widget child, {List<dynamic> overrides = const []}) async {
  SharedPreferences.setMockInitialValues({'locale': 'ru'});
  final prefs = await SharedPreferences.getInstance();
  return ProviderScope(
    retry: (retryCount, error) => null,
    overrides: [
      sharedPreferencesProvider.overrideWithValue(prefs),
      tokenStoreProvider.overrideWithValue(MemoryTokenStore()),
      authRepositoryProvider.overrideWithValue(FakeAuth()),
      ...overrides.cast(),
    ],
    child: child,
  );
}

void main() {
  testWidgets('онбординг: приветствие → код приглашения → вуз и группа', (tester) async {
    await tester.pumpWidget(await app(DoomichApp(shell: (_) => const Text('shell'))));
    await tester.pumpAndSettle();
    expect(find.text('Привет! Я Думыч'), findsOneWidget);
    expect(find.text('Без телефона, почты и имени — только псевдоним.'), findsOneWidget);

    await tester.tap(find.text('Начать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'GOOD-CODE');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.text('Вы присоединяетесь к «Демо-университет»'), findsOneWidget);
    expect(find.textContaining('Группа ИВТ-21-1'), findsOneWidget);

    await tester.tap(find.text('Далее'));
    await tester.pumpAndSettle();
    expect(find.text('Создайте аккаунт'), findsOneWidget);
    // кнопка неактивна, пока нет согласия и пароля
    final button = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Создать аккаунт'));
    expect(button.onPressed, isNull);
  });

  testWidgets('чат: потоковый ответ, статус инструмента и источники', (tester) async {
    final chat = FakeChat();
    await tester.pumpWidget(
      await app(
        Builder(
          builder: (context) => MaterialApp(
            locale: const Locale('ru'),
            supportedLocales: DoomichLocalizations.supportedLocales,
            localizationsDelegates: doomichLocalizationDelegates,
            home: const ChatView(chatKey: ChatKey.incognito('t1')),
          ),
        ),
        overrides: [chatRepositoryProvider.overrideWithValue(chat)],
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Этот чат не сохраняется на сервере'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'Что у меня завтра?');
    await tester.tap(find.byTooltip('Отправить'));
    await tester.pumpAndSettle();
    expect(chat.sent, ['Что у меня завтра?']);
    expect(find.text('Что у меня завтра?'), findsOneWidget);
    expect(find.textContaining('матанализ в 9:00', findRichText: true), findsWidgets);
    expect(find.text('Источники'), findsOneWidget);
    expect(find.textContaining('Расписание.pdf'), findsOneWidget);
  });

  test('настройки сохраняются между запусками', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final container = ProviderContainer(overrides: [sharedPreferencesProvider.overrideWithValue(prefs)]);
    addTearDown(container.dispose);
    await container.read(settingsProvider.notifier).setThemeMode(ThemeMode.dark);
    await container.read(settingsProvider.notifier).setApiBase('https://doomich.example.ru///');
    final fresh = ProviderContainer(overrides: [sharedPreferencesProvider.overrideWithValue(prefs)]);
    addTearDown(fresh.dispose);
    expect(fresh.read(settingsProvider).themeMode, ThemeMode.dark);
    expect(fresh.read(settingsProvider).apiBase, 'https://doomich.example.ru');
  });

  test('isJwtExpired', () {
    String jwt(int exp) {
      final payload = base64UrlNoPad('{"exp":$exp}');
      return 'x.$payload.y';
    }

    final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
    expect(isJwtExpired(jwt(now + 600)), isFalse);
    expect(isJwtExpired(jwt(now - 10)), isTrue);
    expect(isJwtExpired('garbage'), isTrue);
  });
}

String base64UrlNoPad(String s) => base64UrlEncodeNoPad(s.codeUnits);

String base64UrlEncodeNoPad(List<int> bytes) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  final out = StringBuffer();
  for (var i = 0; i < bytes.length; i += 3) {
    final chunk = (bytes[i] << 16) | ((i + 1 < bytes.length ? bytes[i + 1] : 0) << 8) | (i + 2 < bytes.length ? bytes[i + 2] : 0);
    final n = i + 2 < bytes.length ? 4 : (i + 1 < bytes.length ? 3 : 2);
    for (var j = 0; j < n; j++) {
      out.write(chars[(chunk >> (18 - 6 * j)) & 63]);
    }
  }
  return out.toString();
}
