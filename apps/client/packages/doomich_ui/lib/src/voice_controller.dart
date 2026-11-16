import 'dart:async';
import 'package:doomich_core/doomich_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'audio.dart';
import 'chat_controller.dart';
import 'providers.dart';
import 'settings.dart';

enum VoiceStatus { idle, connecting, listening, thinking, speaking, error }

@immutable
class VoiceState {
  const VoiceState({this.status = VoiceStatus.idle, this.transcript = '', this.answer = '', this.error});

  final VoiceStatus status;
  final String transcript;
  final String answer;
  final String? error;

  VoiceState copyWith({VoiceStatus? status, String? transcript, String? answer, String? error, bool clearError = false}) =>
      VoiceState(
        status: status ?? this.status,
        transcript: transcript ?? this.transcript,
        answer: answer ?? this.answer,
        error: clearError ? null : (error ?? this.error),
      );
}

/// Голосовой диалог «нажми-и-говори»: запись → WebSocket → расшифровка → ответ → озвучка.
class VoiceController extends Notifier<VoiceState> {
  final VoiceRecorder _recorder = VoiceRecorder();
  final SpeechPlayer _player = SpeechPlayer();
  VoiceClient? _client;
  StreamSubscription<VoiceEvent>? _events;
  ChatKey? _chat;

  @override
  VoiceState build() {
    _player.onIdle.listen((_) {
      if (ref.mounted && state.status == VoiceStatus.speaking) state = state.copyWith(status: VoiceStatus.idle);
    });
    ref.onDispose(() async {
      await _events?.cancel();
      await _client?.close();
      await _recorder.dispose();
      await _player.dispose();
    });
    return const VoiceState();
  }

  Uri _wsUrl() {
    final base = Uri.parse(ref.read(settingsProvider).apiBase);
    return base.replace(scheme: base.scheme == 'https' ? 'wss' : 'ws', path: '/v1/voice');
  }

  Future<void> _ensureConnected() async {
    if (_client != null) return;
    final token = await freshAccessToken(ref.read(apiClientProvider));
    if (token == null) throw const ApiException('Сессия истекла, войдите снова', status: 401);
    final client = await VoiceClient.connect(_wsUrl(), token);
    _client = client;
    _events = client.events.listen(_onEvent, onDone: () {
      _client = null;
      _events = null;
    });
  }

  /// Начать запись. [chat] — куда сохранить диалог (для инкогнито передаётся история с устройства).
  Future<void> startListening({ChatKey? chat, List<ChatMessage> history = const []}) async {
    if (state.status == VoiceStatus.listening) return;
    await _player.stop();
    _chat = chat;
    state = const VoiceState(status: VoiceStatus.connecting);
    try {
      if (!await _recorder.hasPermission()) {
        state = state.copyWith(status: VoiceStatus.error, error: 'mic');
        return;
      }
      await _ensureConnected();
      final settings = ref.read(settingsProvider);
      final me = ref.read(sessionProvider).value;
      _client!.start(
        chatId: chat?.chatId,
        lang: settings.locale?.languageCode ?? me?.locale ?? 'ru',
        speak: settings.autoSpeak && await _player.isAvailable,
        speed: settings.voiceSpeed,
        history: chat?.chatId == null ? history : const [],
      );
      await _recorder.start((Uint8List chunk) => _client?.sendAudio(chunk));
      state = state.copyWith(status: VoiceStatus.listening);
    } catch (e) {
      state = state.copyWith(status: VoiceStatus.error, error: e.toString());
    }
  }

  Future<void> stopListening() async {
    if (state.status != VoiceStatus.listening) return;
    await _recorder.stop();
    _client?.end();
    state = state.copyWith(status: VoiceStatus.thinking);
  }

  Future<void> cancel() async {
    await _recorder.stop();
    await _player.stop();
    _client?.cancel();
    state = const VoiceState();
  }

  void _onEvent(VoiceEvent event) {
    if (!ref.mounted) return;
    switch (event) {
      case VoiceTranscript(:final text):
        state = state.copyWith(transcript: text);
      case VoiceAnswerDelta(:final text):
        state = state.copyWith(answer: state.answer + text);
      case VoiceAudio(:final bytes, :final format):
        state = state.copyWith(status: VoiceStatus.speaking);
        _player.setRate(ref.read(settingsProvider).voiceSpeed);
        _player.enqueue(bytes, format: format);
      case VoiceDone(:final text, :final messageId):
        final chat = _chat;
        if (chat != null && state.transcript.isNotEmpty) {
          ref.read(chatControllerProvider(chat).notifier).appendVoiceTurn(state.transcript, text, messageId: messageId);
        }
        if (!_player.isPlaying) state = state.copyWith(status: VoiceStatus.idle, answer: text);
      case VoiceError(:final message):
        state = state.copyWith(status: VoiceStatus.error, error: message);
      case VoiceReady() || VoiceTool() || VoiceCitations():
        break;
    }
  }
}

final voiceControllerProvider = NotifierProvider<VoiceController, VoiceState>(VoiceController.new);
