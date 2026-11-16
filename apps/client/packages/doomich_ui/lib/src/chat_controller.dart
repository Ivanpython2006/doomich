import 'dart:async';

import 'package:doomich_core/doomich_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'providers.dart';

/// Ключ чата: идентификатор на сервере или «incognito:…» для чата без сохранения.
@immutable
class ChatKey {
  const ChatKey.server(String this.chatId, {this.documentIds = const []}) : incognitoId = null;
  const ChatKey.incognito(String this.incognitoId, {this.documentIds = const []}) : chatId = null;

  final String? chatId;
  final String? incognitoId;
  final List<String> documentIds;

  bool get isIncognito => chatId == null;

  @override
  bool operator ==(Object other) => other is ChatKey && other.chatId == chatId && other.incognitoId == incognitoId;

  @override
  int get hashCode => Object.hash(chatId, incognitoId);
}

@immutable
class ChatState {
  const ChatState({this.messages = const [], this.loading = false, this.sending = false, this.tool, this.error});

  final List<ChatMessage> messages;
  final bool loading;
  final bool sending;
  final String? tool;
  final String? error;

  ChatState copyWith({List<ChatMessage>? messages, bool? loading, bool? sending, String? tool, bool clearTool = false, String? error, bool clearError = false}) =>
      ChatState(
        messages: messages ?? this.messages,
        loading: loading ?? this.loading,
        sending: sending ?? this.sending,
        tool: clearTool ? null : (tool ?? this.tool),
        error: clearError ? null : (error ?? this.error),
      );
}

class ChatController extends Notifier<ChatState> {
  ChatController(this.key);

  final ChatKey key;
  CancelToken? _cancel;
  int _localIds = 0;

  @override
  ChatState build() {
    ref.onDispose(() => _cancel?.cancel());
    if (!key.isIncognito) {
      Future.microtask(load);
      return const ChatState(loading: true);
    }
    return const ChatState();
  }

  ChatRepository get _repo => ref.read(chatRepositoryProvider);

  Future<void> load() async {
    if (key.isIncognito) return;
    try {
      final messages = await _repo.messages(key.chatId!);
      if (ref.mounted) state = state.copyWith(messages: messages, loading: false, clearError: true);
    } on ApiException catch (e) {
      if (ref.mounted) state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> send(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || state.sending) return;
    final history = List<ChatMessage>.of(state.messages);
    final user = ChatMessage(id: 'local-${_localIds++}', author: 'user', content: trimmed);
    final answer = ChatMessage(id: 'local-${_localIds++}', author: 'assistant', content: '');
    state = state.copyWith(messages: [...history, user, answer], sending: true, clearError: true, clearTool: true);
    _cancel = CancelToken();
    final stream = key.isIncognito
        ? _repo.incognito(trimmed, history: history, documentIds: key.documentIds, cancel: _cancel)
        : _repo.send(key.chatId!, trimmed, cancel: _cancel);
    try {
      await for (final event in stream) {
        if (!ref.mounted) return;
        switch (event) {
          case ChatDelta(:final text):
            answer.content += text;
            state = state.copyWith(messages: [...state.messages], clearTool: true);
          case ChatTool(:final name):
            state = state.copyWith(tool: name);
          case ChatCitations(:final citations):
            answer.citations = citations;
          case ChatDone(:final text, :final messageId, :final citations):
            final done = ChatMessage(
              id: messageId ?? answer.id,
              author: 'assistant',
              content: text.isEmpty ? answer.content : text,
              citations: citations.isEmpty ? answer.citations : citations,
            );
            state = state.copyWith(
              messages: [for (final m in state.messages) identical(m, answer) ? done : m],
              sending: false,
              clearTool: true,
            );
          case ChatError(:final message):
            state = state.copyWith(error: message);
        }
      }
    } on ApiException catch (e) {
      if (ref.mounted) state = state.copyWith(error: e.message);
    } finally {
      if (ref.mounted) {
        state = state.copyWith(
          sending: false,
          clearTool: true,
          messages: [for (final m in state.messages) if (!(identical(m, answer) && m.content.isEmpty)) m],
        );
      }
      if (!key.isIncognito) unawaited(ref.read(chatListProvider.notifier).refresh().catchError((_) {}));
    }
  }

  void stop() {
    _cancel?.cancel();
    state = state.copyWith(sending: false, clearTool: true);
  }

  /// Добавить сообщения, пришедшие по голосовому каналу.
  void appendVoiceTurn(String question, String answerText, {String? messageId, List<Citation> citations = const []}) {
    state = state.copyWith(
      messages: [
        ...state.messages,
        ChatMessage(id: 'local-${_localIds++}', author: 'user', content: question, mode: 'voice'),
        ChatMessage(id: messageId ?? 'local-${_localIds++}', author: 'assistant', content: answerText, citations: citations, mode: 'voice'),
      ],
    );
  }

  Future<void> rate(ChatMessage message, int rating, {bool includeDialog = false}) =>
      _repo.feedback(messageId: message.id.startsWith('local-') ? null : message.id, rating: rating, includeDialog: includeDialog);
}

final chatControllerProvider = NotifierProvider.autoDispose.family<ChatController, ChatState, ChatKey>(ChatController.new);
