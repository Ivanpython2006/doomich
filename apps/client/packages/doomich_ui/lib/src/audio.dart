import 'dart:async';
import 'dart:collection';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// Запись голоса: PCM16, 16 кГц, моно — потоком кадров для голосового канала.
///
/// Нативный рекордер создаётся только при первой записи.
class VoiceRecorder {
  AudioRecorder? _instance;
  StreamSubscription<Uint8List>? _sub;

  AudioRecorder get _recorder => _instance ??= AudioRecorder();

  Future<bool> hasPermission() => _recorder.hasPermission();

  Future<void> start(void Function(Uint8List chunk) onChunk) async {
    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
      ),
    );
    _sub = stream.listen(onChunk);
  }

  Future<void> stop() async {
    final recorder = _instance;
    if (recorder == null) return;
    await recorder.stop();
    await _sub?.cancel();
    _sub = null;
  }

  Future<void> dispose() async {
    final recorder = _instance;
    if (recorder == null) return;
    await stop();
    await recorder.dispose();
    _instance = null;
  }
}

/// Способ воспроизведения звука на этом устройстве.
abstract class PlaybackBackend {
  /// Проиграть фрагмент. Завершается, когда фрагмент доигран или остановлен.
  Future<void> play(Uint8List bytes, String format, double rate);

  Future<void> stop();

  Future<void> dispose();
}

typedef PlaybackFactory = Future<PlaybackBackend?> Function();

/// Выбор способа воспроизведения.
///
/// На Linux плагин audioplayers работает через GStreamer и аварийно завершает всё приложение,
/// если в системе нет нужных плагинов GStreamer (исключение из нативного кода не перехватить).
/// Поэтому сначала проверяем плагины, а без них проигрываем внешней утилитой
/// (pw-play, paplay, ffplay или aplay). `DOOMICH_AUDIO=gstreamer|process` — принудительный выбор.
Future<PlaybackBackend?> defaultPlaybackBackend() async {
  if (kIsWeb) return null;
  if (!Platform.isLinux) return PluginPlayback();
  final forced = Platform.environment['DOOMICH_AUDIO'];
  if (forced == 'gstreamer' || (forced != 'process' && linuxGstreamerPlaybackAvailable())) {
    return PluginPlayback();
  }
  final command = linuxPlayerCommand();
  return command == null ? null : ProcessPlayback(command);
}

/// Есть ли плагины GStreamer, без которых audioplayers не сыграет WAV:
/// playbin (plugins-base), wavparse и autoaudiosink (plugins-good).
bool linuxGstreamerPlaybackAvailable({Map<String, String>? environment}) {
  final env = environment ?? Platform.environment;
  List<String> paths(String key) => (env[key] ?? '').split(':').where((p) => p.isNotEmpty).toList();
  final system = [...paths('GST_PLUGIN_SYSTEM_PATH_1_0'), ...paths('GST_PLUGIN_SYSTEM_PATH')];
  final dirs = [
    ...paths('GST_PLUGIN_PATH_1_0'),
    ...paths('GST_PLUGIN_PATH'),
    if (env['HOME'] != null) '${env['HOME']}/.local/share/gstreamer-1.0/plugins',
    if (system.isNotEmpty)
      ...system
    else ...const [
      '/usr/lib/x86_64-linux-gnu/gstreamer-1.0',
      '/usr/lib/aarch64-linux-gnu/gstreamer-1.0',
      '/usr/lib64/gstreamer-1.0',
      '/usr/lib/gstreamer-1.0',
      '/usr/local/lib/gstreamer-1.0',
      '/app/lib/gstreamer-1.0',
    ],
  ];
  bool has(String plugin) => dirs.any((dir) => File('$dir/libgst$plugin.so').existsSync());
  return has('playback') && has('wavparse') && has('autodetect');
}

/// Первая найденная утилита воспроизведения (Linux).
List<String>? linuxPlayerCommand({String? path}) {
  const candidates = [
    ['pw-play'],
    ['paplay'],
    ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet'],
    ['aplay', '-q'],
  ];
  final dirs = (path ?? Platform.environment['PATH'] ?? '/usr/bin:/bin').split(':').where((d) => d.isNotEmpty);
  for (final candidate in candidates) {
    for (final dir in dirs) {
      final file = File('$dir/${candidate.first}');
      if (file.existsSync()) return [file.path, ...candidate.skip(1)];
    }
  }
  return null;
}

Future<File> _speechFile(String format, int n) async {
  final dir = await getTemporaryDirectory();
  final ext = RegExp(r'^[a-z0-9]{1,5}$').hasMatch(format) ? format : 'bin';
  return File('${dir.path}/doomich_tts_${n % 4}.$ext');
}

/// Воспроизведение через плагин audioplayers (Android, Windows, Linux с GStreamer).
class PluginPlayback implements PlaybackBackend {
  PluginPlayback() {
    _completion = _player.onPlayerComplete.listen((_) => _finish(), onError: (Object _) => _finish());
  }

  final AudioPlayer _player = AudioPlayer();
  late final StreamSubscription<void> _completion;
  Completer<void>? _current;
  int _counter = 0;

  void _finish() {
    final current = _current;
    _current = null;
    if (current != null && !current.isCompleted) current.complete();
  }

  @override
  Future<void> play(Uint8List bytes, String format, double rate) async {
    _finish();
    final done = _current = Completer<void>();
    try {
      if (Platform.isAndroid || Platform.isIOS) {
        await _player.play(BytesSource(bytes, mimeType: 'audio/$format'));
      } else {
        // на ПК надёжнее проигрывать из временного файла
        final file = await _speechFile(format, _counter++);
        await file.writeAsBytes(bytes, flush: true);
        await _player.play(DeviceFileSource(file.path));
      }
      if (rate != 1.0) await _player.setPlaybackRate(rate);
    } catch (_) {
      _finish();
      rethrow;
    }
    return done.future;
  }

  @override
  Future<void> stop() async {
    _finish();
    await _player.stop();
  }

  @override
  Future<void> dispose() async {
    _finish();
    await _completion.cancel();
    await _player.dispose();
  }
}

/// Воспроизведение внешней утилитой (Linux без плагинов GStreamer).
class ProcessPlayback implements PlaybackBackend {
  ProcessPlayback(this.command);

  final List<String> command;
  Process? _process;
  int _counter = 0;

  @override
  Future<void> play(Uint8List bytes, String format, double rate) async {
    final file = await _speechFile(format, _counter++);
    await file.writeAsBytes(bytes, flush: true);
    final tempo = rate != 1.0 && command.first.endsWith('ffplay')
        ? ['-af', 'atempo=${rate.clamp(0.5, 2.0)}']
        : const <String>[];
    final process = _process = await Process.start(command.first, [...command.skip(1), ...tempo, file.path]);
    unawaited(process.stdout.drain<void>());
    unawaited(process.stderr.drain<void>());
    await process.exitCode;
    if (identical(_process, process)) _process = null;
  }

  @override
  Future<void> stop() async {
    _process?.kill();
    _process = null;
  }

  @override
  Future<void> dispose() => stop();
}

/// Очередь воспроизведения фрагментов озвучки (по предложению на фрагмент).
///
/// Способ воспроизведения выбирается при первом обращении, а не при создании:
/// экран чата не должен зависеть от звуковой подсистемы, пока звук не нужен.
class SpeechPlayer {
  SpeechPlayer({PlaybackFactory? backend}) : _factory = backend ?? defaultPlaybackBackend;

  final PlaybackFactory _factory;
  Future<PlaybackBackend?>? _backend;
  final Queue<(Uint8List, String)> _queue = Queue();
  final _idle = StreamController<void>.broadcast();
  bool _pumping = false;
  bool _disposed = false;
  double _rate = 1.0;

  /// Сигнал «всё проиграно».
  Stream<void> get onIdle => _idle.stream;
  bool get isPlaying => _pumping;

  Future<PlaybackBackend?> _resolve() => _backend ??= _factory();

  /// Можно ли проигрывать звук на этом устройстве.
  Future<bool> get isAvailable async => await _resolve() != null;

  /// Скорость применяется со следующего фрагмента.
  Future<void> setRate(double rate) async => _rate = rate;

  void enqueue(Uint8List bytes, {String format = 'wav'}) {
    if (_disposed) return;
    _queue.add((bytes, format));
    unawaited(_pump());
  }

  Future<void> _pump() async {
    if (_pumping || _disposed) return;
    _pumping = true;
    try {
      final backend = await _resolve();
      while (_queue.isNotEmpty && !_disposed) {
        final (bytes, format) = _queue.removeFirst();
        if (backend == null) continue;
        try {
          await backend.play(bytes, format, _rate);
        } catch (e) {
          debugPrint('Озвучка: $e');
        }
      }
    } finally {
      _pumping = false;
      if (!_disposed) _idle.add(null);
    }
  }

  Future<void> stop() async {
    _queue.clear();
    final backend = await _backend;
    await backend?.stop();
  }

  Future<void> dispose() async {
    _disposed = true;
    _queue.clear();
    final backend = await _backend;
    await backend?.dispose();
    await _idle.close();
  }
}
