import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:doomich_ui/doomich_ui.dart';
import 'package:flutter_test/flutter_test.dart';

/// Подменный способ воспроизведения: фрагмент «играет», пока тест не завершит его.
class FakePlayback implements PlaybackBackend {
  final played = <String>[];
  final rates = <double>[];
  Completer<void>? current;
  int stops = 0;
  bool disposed = false;

  @override
  Future<void> play(Uint8List bytes, String format, double rate) {
    played.add('${bytes.first}.$format');
    rates.add(rate);
    return (current = Completer<void>()).future;
  }

  void finishCurrent() => current?.complete();

  @override
  Future<void> stop() async {
    stops++;
    if (current?.isCompleted == false) current!.complete();
  }

  @override
  Future<void> dispose() async => disposed = true;
}

Uint8List clip(int id) => Uint8List.fromList([id, 0, 0, 0]);

void main() {
  test('фрагменты играют по очереди, затем приходит сигнал «всё проиграно»', () async {
    final backend = FakePlayback();
    final player = SpeechPlayer(backend: () async => backend);
    final idle = player.onIdle.first;
    await player.setRate(1.25);
    player
      ..enqueue(clip(1))
      ..enqueue(clip(2), format: 'ogg');
    await pumpEventQueue();
    expect(backend.played, ['1.wav']);
    expect(player.isPlaying, isTrue);

    backend.finishCurrent();
    await pumpEventQueue();
    expect(backend.played, ['1.wav', '2.ogg']);
    expect(backend.rates, [1.25, 1.25]);

    backend.finishCurrent();
    await idle;
    expect(player.isPlaying, isFalse);
  });

  test('стоп очищает очередь, а новый фрагмент после стопа всё равно играет', () async {
    final backend = FakePlayback();
    final player = SpeechPlayer(backend: () async => backend);
    player
      ..enqueue(clip(1))
      ..enqueue(clip(2));
    await pumpEventQueue();
    await player.stop();
    player.enqueue(clip(3));
    await pumpEventQueue();
    expect(backend.played, ['1.wav', '3.wav']);
    expect(backend.stops, 1);
    await player.dispose();
    expect(backend.disposed, isTrue);
  });

  test('способ воспроизведения не создаётся, пока звук не нужен', () async {
    var created = 0;
    final player = SpeechPlayer(backend: () async {
      created++;
      return FakePlayback();
    });
    await player.stop();
    await player.dispose();
    expect(created, 0);
  });

  test('без проигрывателя озвучка недоступна, а очередь не зависает', () async {
    final player = SpeechPlayer(backend: () async => null);
    expect(await player.isAvailable, isFalse);
    final idle = player.onIdle.first;
    player.enqueue(clip(1));
    await idle;
    expect(player.isPlaying, isFalse);
  });

  group('Linux', () {
    late Directory tmp;
    setUp(() => tmp = Directory.systemTemp.createTempSync('doomich_audio'));
    tearDown(() => tmp.deleteSync(recursive: true));

    test('плагины GStreamer ищутся по путям из окружения', () {
      final plugins = Directory('${tmp.path}/gst')..createSync();
      final env = {'GST_PLUGIN_SYSTEM_PATH_1_0': plugins.path};
      for (final name in ['playback', 'wavparse']) {
        File('${plugins.path}/libgst$name.so').writeAsStringSync('');
      }
      expect(linuxGstreamerPlaybackAvailable(environment: env), isFalse, reason: 'нет autoaudiosink');
      File('${plugins.path}/libgstautodetect.so').writeAsStringSync('');
      expect(linuxGstreamerPlaybackAvailable(environment: env), isTrue);
    });

    test('утилита воспроизведения выбирается по приоритету', () {
      final bin = Directory('${tmp.path}/bin')..createSync();
      expect(linuxPlayerCommand(path: bin.path), isNull);
      File('${bin.path}/aplay').writeAsStringSync('');
      expect(linuxPlayerCommand(path: bin.path), ['${bin.path}/aplay', '-q']);
      File('${bin.path}/paplay').writeAsStringSync('');
      expect(linuxPlayerCommand(path: bin.path), ['${bin.path}/paplay']);
    });
  });
}
