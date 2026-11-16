import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'models.dart';

/// События голосового канала (протокол — services/api/src/doomich_api/api/voice.py).
sealed class VoiceEvent {
  const VoiceEvent();
}

class VoiceReady extends VoiceEvent {
  const VoiceReady();
}

class VoiceTranscript extends VoiceEvent {
  const VoiceTranscript(this.text, {this.language});
  final String text;
  final String? language;
}

class VoiceAnswerDelta extends VoiceEvent {
  const VoiceAnswerDelta(this.text);
  final String text;
}

class VoiceTool extends VoiceEvent {
  const VoiceTool(this.name);
  final String name;
}

class VoiceAudio extends VoiceEvent {
  const VoiceAudio({required this.seq, required this.format, required this.sampleRate, required this.bytes, this.text});
  final int seq;
  final String format;
  final int sampleRate;
  final Uint8List bytes;
  final String? text;
}

class VoiceCitations extends VoiceEvent {
  const VoiceCitations(this.citations);
  final List<Citation> citations;
}

class VoiceDone extends VoiceEvent {
  const VoiceDone({required this.text, this.messageId});
  final String text;
  final String? messageId;
}

class VoiceError extends VoiceEvent {
  const VoiceError(this.code, this.message);
  final String code;
  final String message;
}

/// Сессия голосового общения поверх WebSocket.
///
/// Звук отправляется кадрами PCM16 16 кГц (или сжатым — формат указывается в [start]).
class VoiceClient {
  VoiceClient._(this._channel) {
    _sub = _channel.stream.listen(_onMessage, onError: (Object e) {
      _events.add(VoiceError('network', e.toString()));
    }, onDone: () => _events.close());
  }

  static Future<VoiceClient> connect(Uri wsUrl, String accessToken) async {
    final channel = WebSocketChannel.connect(wsUrl);
    await channel.ready;
    final client = VoiceClient._(channel);
    channel.sink.add(jsonEncode({'type': 'auth', 'token': accessToken}));
    return client;
  }

  /// Для тестов: сессия поверх готового канала.
  factory VoiceClient.withChannel(WebSocketChannel channel) => VoiceClient._(channel);

  final WebSocketChannel _channel;
  late final StreamSubscription<dynamic> _sub;
  final _events = StreamController<VoiceEvent>.broadcast();
  Map<String, dynamic>? _pendingAudio;

  Stream<VoiceEvent> get events => _events.stream;

  void start({
    String? chatId,
    String lang = 'ru',
    String format = 'pcm16',
    int sampleRate = 16000,
    bool speak = true,
    double speed = 1.0,
    List<ChatMessage> history = const [],
  }) {
    _send({
      'type': 'start',
      'chat_id': chatId,
      'lang': lang,
      'format': format,
      'sample_rate': sampleRate,
      'speak': speak,
      'speed': speed,
      if (chatId == null) 'history': history.map((m) => m.toHistory()).toList(),
    });
  }

  void sendAudio(Uint8List chunk) => _channel.sink.add(chunk);

  void end() => _send({'type': 'end'});

  void cancel() => _send({'type': 'cancel'});

  void _send(Map<String, dynamic> message) => _channel.sink.add(jsonEncode(message));

  void _onMessage(dynamic raw) {
    if (raw is List<int>) {
      final meta = _pendingAudio;
      _pendingAudio = null;
      if (meta != null) {
        _events.add(
          VoiceAudio(
            seq: meta['seq'] as int,
            format: meta['format'] as String,
            sampleRate: meta['sample_rate'] as int,
            text: meta['text'] as String?,
            bytes: raw is Uint8List ? raw : Uint8List.fromList(raw),
          ),
        );
      }
      return;
    }
    final message = jsonDecode(raw as String) as Map<String, dynamic>;
    final event = switch (message['type']) {
      'ready' => const VoiceReady(),
      'transcript' => VoiceTranscript(message['text'] as String? ?? '', language: message['language'] as String?),
      'answer_delta' => VoiceAnswerDelta(message['text'] as String? ?? ''),
      'tool' => VoiceTool(message['name'] as String? ?? ''),
      'citations' => VoiceCitations(
        (message['citations'] as List? ?? const []).map((c) => Citation.fromJson(c as Map<String, dynamic>)).toList(),
      ),
      'done' => VoiceDone(text: message['text'] as String? ?? '', messageId: message['message_id'] as String?),
      'error' => VoiceError(message['code']?.toString() ?? 'error', message['message'] as String? ?? 'Ошибка'),
      _ => null,
    };
    if (message['type'] == 'audio') {
      _pendingAudio = message; // следующий бинарный кадр — звук
    } else if (event != null) {
      _events.add(event);
    }
  }

  Future<void> close() async {
    await _sub.cancel();
    await _channel.sink.close();
    if (!_events.isClosed) await _events.close();
  }
}
