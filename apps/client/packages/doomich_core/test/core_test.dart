import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:async/async.dart' show DelegatingStreamSink;
import 'package:dio/dio.dart';
import 'package:doomich_core/doomich_core.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:test/test.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

/// Подменный транспорт dio: отвечает по сценарию и запоминает запросы.
class FakeAdapter implements HttpClientAdapter {
  FakeAdapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;
  final requests = <RequestOptions>[];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) {
    requests.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody jsonBody(Object data, {int status = 200}) => ResponseBody.fromString(
  jsonEncode(data),
  status,
  headers: {
    Headers.contentTypeHeader: [Headers.jsonContentType],
  },
);

Map<String, dynamic> meJson() => {
  'id': 'u1',
  'login': 'ТихийЕнот42',
  'role': 'student',
  'locale': 'ru',
  'history_days': 90,
  'university': {'id': 'uni', 'slug': 'demo', 'name': 'Демо', 'timezone': 'Europe/Moscow'},
  'group': {'id': 'g1', 'code': 'ИВТ-21-1'},
  'created_on': '2026-11-16',
  'features': {'lectures': true},
};

void main() {
  group('SSE', () {
    test('разбирает события и многострочные данные', () async {
      final raw = 'event: start\ndata: {"chat_id": "c1"}\n\nevent: delta\ndata: {"text": "При"}\n\n'
          'event: delta\ndata: {"text": "вет"}\n\nevent: done\ndata: {"text": "Привет", "message_id": "m1"}\n\n';
      // режем поток в неудобных местах — парсер должен склеить
      final bytes = utf8.encode(raw);
      final chunks = Stream<List<int>>.fromIterable([bytes.sublist(0, 7), bytes.sublist(7, 40), bytes.sublist(40)]);
      final events = await chunks.transform(const SseParser()).toList();
      expect(events.map((e) => e.event), ['start', 'delta', 'delta', 'done']);
      final chat = events.map(chatEventFromSse).whereType<ChatStreamEvent>().toList();
      expect((chat[0] as ChatDelta).text + (chat[1] as ChatDelta).text, 'Привет');
      expect((chat[2] as ChatDone).messageId, 'm1');
    });
  });

  group('ApiClient', () {
    test('при 401 обновляет сессию один раз и повторяет запрос', () async {
      final tokens = MemoryTokenStore();
      await tokens.save('old-access', 'refresh-1');
      var refreshes = 0;
      final adapter = FakeAdapter((o) async {
        if (o.path == '/v1/auth/refresh') {
          refreshes++;
          expect(o.data, {'refresh_token': 'refresh-1'});
          return jsonBody({'access_token': 'new-access', 'refresh_token': 'refresh-2', 'user': meJson()});
        }
        if (o.headers['Authorization'] == 'Bearer old-access') return jsonBody({'detail': 'expired'}, status: 401);
        return jsonBody(meJson());
      });
      final dio = Dio()..httpClientAdapter = adapter;
      final api = ApiClient(baseUrl: Uri.parse('http://test'), tokens: tokens, dio: dio);
      final results = await Future.wait([AuthRepository(api).me(), AuthRepository(api).me()]);
      expect(results.map((m) => m.group!.code), ['ИВТ-21-1', 'ИВТ-21-1']);
      expect(refreshes, 1);
      expect(await tokens.readRefresh(), 'refresh-2');
    });

    test('ошибки сервера превращаются в понятные сообщения', () async {
      final dio = Dio()
        ..httpClientAdapter = FakeAdapter((o) async => jsonBody({'detail': 'Такой псевдоним уже занят'}, status: 409));
      final api = ApiClient(baseUrl: Uri.parse('http://test'), tokens: MemoryTokenStore(), dio: dio);
      expect(
        () => AuthRepository(api).register(inviteCode: 'AAAA-BBBB', login: 'x', password: 'y'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', 'Такой псевдоним уже занят').having((e) => e.status, 'status', 409)),
      );
    });

    test('регистрация сохраняет токены и отдаёт код восстановления', () async {
      final tokens = MemoryTokenStore();
      final dio = Dio()
        ..httpClientAdapter = FakeAdapter(
          (o) async => jsonBody({'access_token': 'a', 'refresh_token': 'r', 'user': meJson(), 'recovery_code': 'AAAA-BBBB-CCCC-DDDD-EEEE'}),
        );
      final api = ApiClient(baseUrl: Uri.parse('http://test'), tokens: tokens, dio: dio);
      final result = await AuthRepository(api).register(inviteCode: 'AAAA-BBBB', login: 'ТихийЕнот42', password: 'pass-word-12');
      expect(result.recoveryCode, 'AAAA-BBBB-CCCC-DDDD-EEEE');
      expect(result.user.feature('lectures'), isTrue);
      expect(await tokens.readAccess(), 'a');
    });
  });

  group('Голосовой протокол', () {
    test('аудиокадр приходит после метаданных', () async {
      final toClient = StreamController<dynamic>();
      final fromClient = StreamController<dynamic>();
      final channel = _FakeWebSocket(StreamChannel(toClient.stream, fromClient.sink));
      final client = VoiceClient.withChannel(channel);
      final events = <VoiceEvent>[];
      final sub = client.events.listen(events.add);
      client.start(chatId: 'c1', lang: 'ru');
      client.sendAudio(Uint8List.fromList([1, 2, 3, 4]));
      client.end();
      toClient
        ..add(jsonEncode({'type': 'transcript', 'text': 'какая пара', 'final': true}))
        ..add(jsonEncode({'type': 'answer_delta', 'text': 'Математика'}))
        ..add(jsonEncode({'type': 'audio', 'seq': 0, 'format': 'wav', 'sample_rate': 24000, 'text': 'Математика'}))
        ..add(Uint8List.fromList([82, 73, 70, 70]))
        ..add(jsonEncode({'type': 'done', 'text': 'Математика', 'message_id': 'm1'}));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(events.whereType<VoiceTranscript>().single.text, 'какая пара');
      final audio = events.whereType<VoiceAudio>().single;
      expect(audio.bytes, [82, 73, 70, 70]);
      expect(audio.sampleRate, 24000);
      expect(events.last, isA<VoiceDone>());
      final sent = await fromClient.stream.take(3).toList();
      expect(jsonDecode(sent[0] as String)['type'], 'start');
      expect(sent[1], [1, 2, 3, 4]);
      expect(jsonDecode(sent[2] as String)['type'], 'end');
      await sub.cancel();
    });
  });

  group('Утилиты', () {
    test('псевдонимы и проверка имён', () {
      expect(Pseudonyms.suggest('ru', count: 3), hasLength(3));
      expect(looksLikeRealName('Иван Петров'), isTrue);
      expect(looksLikeRealName('ТихийЕнот42'), isFalse);
    });

    test('код приглашения из QR', () {
      expect(inviteCodeFromQr('doomich://invite/AB2C-DE3F'), 'AB2C-DE3F');
      expect(inviteCodeFromQr('https://doomich.example/invite/ab2c-de3f'), 'AB2C-DE3F');
      expect(inviteCodeFromQr('AB2CDE3F'), 'AB2CDE3F');
      expect(inviteCodeFromQr('просто текст'), isNull);
    });

    test('время пар — по часам вуза, а не устройства', () {
      final start = wallClock('2026-11-16T09:00:00+03:00');
      expect([start.hour, start.minute, start.day], [9, 0, 16]);
      expect(wallClock('2026-11-16T23:30:00.000-05:00').day, 16);
      // UTC и время без смещения (старый сервер) — по поясу устройства, как раньше
      expect(wallClock('2026-11-16T06:00:00Z'), DateTime.utc(2026, 11, 16, 6).toLocal());

      final moscow = University.fromJson({
        'id': 'u', 'slug': 'demo', 'name': 'Демо', 'timezone': 'Europe/Moscow', 'utc_offset_minutes': 180,
      });
      final now = wallNow(moscow.utcOffset, now: DateTime.utc(2026, 11, 16, 22, 30));
      expect([now.day, now.hour, now.minute], [17, 1, 30]);
      final event = ScheduleEvent.fromJson({
        'id': 'e', 'uid': 'x', 'subject': 'Матанализ',
        'starts_at': '2026-11-17T09:00:00+03:00', 'ends_at': '2026-11-17T10:30:00+03:00',
      });
      expect(event.startsAt.isAfter(now), isTrue);
      expect(event.isNow(DateTime(2026, 11, 17, 9, 15)), isTrue);
    });

    test('стойкость пароля', () {
      expect(passwordStrength('short'), 0);
      expect(passwordStrength('очень-надёжный-Пароль-2026'), greaterThanOrEqualTo(3));
    });
  });
}

class _FakeWebSocket extends StreamChannelMixin<dynamic> implements WebSocketChannel {
  _FakeWebSocket(this._inner);

  final StreamChannel<dynamic> _inner;

  @override
  Stream<dynamic> get stream => _inner.stream;

  @override
  WebSocketSink get sink => _FakeSink(_inner.sink);

  @override
  Future<void> get ready => Future.value();

  @override
  String? get protocol => null;

  @override
  int? get closeCode => null;

  @override
  String? get closeReason => null;
}

class _FakeSink extends DelegatingStreamSink<dynamic> implements WebSocketSink {
  _FakeSink(super.sink);

  @override
  Future<void> close([int? closeCode, String? closeReason]) => super.close();
}
