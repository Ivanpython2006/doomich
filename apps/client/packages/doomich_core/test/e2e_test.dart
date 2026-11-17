// Сквозная проверка клиентского ядра против настоящего сервера.
//
// Запуск (сервер с демо-данными: doomich-api seed-demo):
//   DOOMICH_E2E_API=http://localhost:8000 DOOMICH_E2E_INVITE=XXXX-XXXX dart test test/e2e_test.dart
@Tags(['e2e'])
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:doomich_core/doomich_core.dart';
import 'package:test/test.dart';

void main() {
  final api = Platform.environment['DOOMICH_E2E_API'];
  final invite = Platform.environment['DOOMICH_E2E_INVITE'];
  final skip = api == null || invite == null ? 'нужны DOOMICH_E2E_API и DOOMICH_E2E_INVITE' : null;

  test('регистрация, чат, расписание, документы и голос на живом сервере', () async {
    final client = ApiClient(baseUrl: Uri.parse(api!), tokens: MemoryTokenStore());
    final auth = AuthRepository(client);

    final info = await auth.checkInvite(invite!);
    expect(info.valid, isTrue);

    final login = 'Енот${DateTime.now().millisecondsSinceEpoch % 100000}';
    final result = await auth.register(inviteCode: invite, login: login, password: 'очень-надёжный-пароль-1');
    expect(result.recoveryCode, isNotNull);
    expect(result.user.group, isNotNull);

    // расписание демо-группы на текущую неделю
    final schedule = ScheduleRepository(client);
    final now = DateTime.now();
    final monday = DateTime(now.year, now.month, now.day).subtract(Duration(days: now.weekday - 1));
    final week = await schedule.events(monday, monday.add(const Duration(days: 6)));
    expect(week.events, isNotEmpty);

    // чат: инструмент расписания и потоковый ответ
    final chats = ChatRepository(client);
    final chat = await chats.create();
    final events = await chats.send(chat.id, 'Какое у меня расписание на сегодня?').toList();
    expect(events.whereType<ChatTool>().map((e) => e.name), contains('get_schedule'));
    final done = events.whereType<ChatDone>().single;
    expect(done.messageId, isNotNull);
    final history = await chats.messages(chat.id);
    expect(history.map((m) => m.author), ['user', 'assistant']);

    // документ → вопрос по нему со ссылкой на источник
    final docs = DocumentsRepository(client);
    var doc = await docs.upload('конспект.md', utf8.encode('# Интегралы\nИнтеграл — это площадь под графиком функции.'));
    // с воркерами Celery документ разбирается в фоне, без них (dev) — сразу
    for (var i = 0; i < 60 && doc.status != 'ready' && doc.status != 'error'; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      doc = await docs.get(doc.id);
    }
    expect(doc.status, 'ready');
    final docChat = await chats.create(documentIds: [doc.id]);
    final answer = await chats.send(docChat.id, 'Что такое интеграл по документу?').toList();
    final citations = answer.whereType<ChatDone>().single.citations;
    expect(citations, isNotEmpty);
    final source = await docs.chunk(citations.first.documentId, citations.first.chunkId);
    expect(source.body, contains('площадь'));

    // озвучка
    final audio = await SpeechRepository(client).speak('Привет!');
    expect(String.fromCharCodes(audio.sublist(0, 4)), 'RIFF');

    // голосовой канал: звук → расшифровка → ответ → аудио
    final ws = Uri.parse(api).replace(scheme: api.startsWith('https') ? 'wss' : 'ws', path: '/v1/voice');
    final voice = await VoiceClient.connect(ws, (await client.tokens.readAccess())!);
    final voiceEvents = <VoiceEvent>[];
    final finished = voice.events.firstWhere((e) => e is VoiceDone || e is VoiceError);
    voice.events.listen(voiceEvents.add);
    voice.start(chatId: chat.id);
    final pcm = Uint8List(32000); // секунда «тишины с шумом» 16 кГц PCM16
    for (var i = 0; i < pcm.length; i += 2) {
      pcm[i] = (i * 37) % 251;
    }
    voice.sendAudio(pcm);
    voice.end();
    final last = await finished.timeout(const Duration(seconds: 20));
    expect(last, isA<VoiceDone>());
    expect(voiceEvents.whereType<VoiceTranscript>(), isNotEmpty);
    expect(voiceEvents.whereType<VoiceAudio>(), isNotEmpty);
    await voice.close();

    await auth.deleteAccount('очень-надёжный-пароль-1');
    expect(() => auth.me(), throwsA(isA<ApiException>()));
  }, skip: skip, timeout: const Timeout(Duration(minutes: 2)));
}
