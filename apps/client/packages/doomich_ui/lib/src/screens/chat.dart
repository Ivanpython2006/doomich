import 'dart:async';

import 'package:doomich_core/doomich_core.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gpt_markdown/gpt_markdown.dart';

import '../audio.dart';
import '../chat_controller.dart';
import '../providers.dart';
import '../settings.dart';
import '../voice_controller.dart';
import '../widgets/common.dart';

final _speechPlayerProvider = Provider.autoDispose<SpeechPlayer>((ref) {
  final player = SpeechPlayer();
  ref.onDispose(player.dispose);
  return player;
});

/// Список чатов: новый чат, инкогнито, переименование и удаление.
class ChatListView extends ConsumerWidget {
  const ChatListView({super.key, required this.onOpen, this.selected});

  final void Function(ChatKey key) onOpen;
  final ChatKey? selected;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final chats = ref.watch(chatListProvider);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          child: Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  icon: const Icon(Icons.add_comment_outlined),
                  label: Text(l10n.newChat),
                  onPressed: () async {
                    final chat = await guarded(context, () => ref.read(chatListProvider.notifier).create());
                    if (chat != null) onOpen(ChatKey.server(chat.id));
                  },
                ),
              ),
              const SizedBox(width: 8),
              IconButton.outlined(
                tooltip: l10n.incognito,
                icon: const Icon(Icons.visibility_off_outlined),
                onPressed: () => onOpen(ChatKey.incognito(DateTime.now().microsecondsSinceEpoch.toString())),
              ),
            ],
          ),
        ),
        Expanded(
          child: AsyncView(
            value: chats,
            onRetry: () => ref.invalidate(chatListProvider),
            builder: (items) => items.isEmpty
                ? EmptyState(icon: Icons.forum_outlined, text: l10n.noChats)
                : RefreshIndicator(
                    onRefresh: () => ref.read(chatListProvider.notifier).refresh(),
                    child: ListView.builder(
                      itemCount: items.length,
                      itemBuilder: (context, i) {
                        final chat = items[i];
                        return ListTile(
                          selected: selected?.chatId == chat.id,
                          leading: Icon(chat.documentIds.isEmpty ? Icons.chat_bubble_outline : Icons.description_outlined),
                          title: Text(chat.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle: Text('${ddmm(chat.updatedAt)} ${hhmm(chat.updatedAt)}'),
                          onTap: () => onOpen(ChatKey.server(chat.id, documentIds: chat.documentIds)),
                          trailing: PopupMenuButton<String>(
                            onSelected: (action) async {
                              if (action == 'rename') {
                                final title = await promptText(context, title: l10n.renameChat, initial: chat.title);
                                if (title != null && title.trim().isNotEmpty && context.mounted) {
                                  await guarded(context, () => ref.read(chatListProvider.notifier).rename(chat.id, title.trim()));
                                }
                              } else if (action == 'delete' && await confirm(context, l10n.deleteChatConfirm, danger: true)) {
                                if (context.mounted) await guarded(context, () => ref.read(chatListProvider.notifier).remove(chat.id));
                              }
                            },
                            itemBuilder: (_) => [
                              PopupMenuItem(value: 'rename', child: Text(l10n.rename)),
                              PopupMenuItem(value: 'delete', child: Text(l10n.delete)),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
          ),
        ),
      ],
    );
  }
}

/// Диалог с Думычем: сообщения, ввод текста, голос «нажми-и-говори», источники.
class ChatView extends ConsumerStatefulWidget {
  const ChatView({super.key, required this.chatKey, this.showAppBar = true});

  final ChatKey chatKey;
  final bool showAppBar;

  @override
  ConsumerState<ChatView> createState() => ChatViewState();
}

class ChatViewState extends ConsumerState<ChatView> {
  final _input = TextEditingController();
  final _focus = FocusNode();

  void send() {
    final text = _input.text;
    if (text.trim().isEmpty) return;
    _input.clear();
    ref.read(chatControllerProvider(widget.chatKey).notifier).send(text);
  }

  /// Вызывается горячей клавишей на ПК.
  Future<void> startVoice() {
    final history = ref.read(chatControllerProvider(widget.chatKey)).messages;
    return ref.read(voiceControllerProvider.notifier).startListening(chat: widget.chatKey, history: history);
  }

  Future<void> stopVoice() => ref.read(voiceControllerProvider.notifier).stopListening();

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final state = ref.watch(chatControllerProvider(widget.chatKey));
    final voice = ref.watch(voiceControllerProvider);
    ref.listen(voiceControllerProvider, (prev, next) {
      if (next.status == VoiceStatus.error && prev?.status != VoiceStatus.error) {
        showMessage(context, next.error == 'mic' ? l10n.micPermission : (next.error ?? l10n.voiceError));
      }
    });
    final title = widget.chatKey.isIncognito ? l10n.incognito : null;
    final body = Column(
      children: [
        if (widget.chatKey.isIncognito)
          MaterialBanner(
            content: Text(l10n.incognitoHint),
            leading: const Icon(Icons.visibility_off_outlined),
            actions: const [SizedBox.shrink()],
          ),
        if (widget.chatKey.documentIds.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Chip(avatar: const Icon(Icons.description_outlined, size: 18), label: Text(l10n.documentScope(widget.chatKey.documentIds.length))),
          ),
        Expanded(
          child: state.loading
              ? const Center(child: CircularProgressIndicator())
              : state.messages.isEmpty
              ? EmptyState(icon: Icons.psychology_alt_outlined, text: l10n.emptyChatHint)
              : ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  itemCount: state.messages.length,
                  itemBuilder: (context, i) {
                    final message = state.messages[state.messages.length - 1 - i];
                    return MessageBubble(message: message, chatKey: widget.chatKey);
                  },
                ),
        ),
        if (state.tool != null || (state.sending && (state.messages.lastOrNull?.content.isEmpty ?? true)))
          _StatusLine(text: _toolText(context, state.tool)),
        if (voice.status != VoiceStatus.idle && voice.status != VoiceStatus.error) _VoicePanel(voice: voice),
        if (state.error != null)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Text(state.error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: CallbackShortcuts(
                    bindings: {const SingleActivator(LogicalKeyboardKey.enter): send},
                    child: TextField(
                      controller: _input,
                      focusNode: _focus,
                      minLines: 1,
                      maxLines: 6,
                      textInputAction: TextInputAction.newline,
                      decoration: InputDecoration(hintText: l10n.inputHint, isDense: true),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                VoiceButton(onStart: startVoice, onStop: stopVoice),
                const SizedBox(width: 2),
                state.sending
                    ? IconButton.filledTonal(
                        tooltip: l10n.stop,
                        icon: const Icon(Icons.stop_rounded),
                        onPressed: () => ref.read(chatControllerProvider(widget.chatKey).notifier).stop(),
                      )
                    : IconButton.filled(tooltip: l10n.send, icon: const Icon(Icons.send_rounded), onPressed: send),
              ],
            ),
          ),
        ),
      ],
    );
    if (!widget.showAppBar) return body;
    return Scaffold(appBar: AppBar(title: Text(title ?? l10n.navChat)), body: body);
  }

  String _toolText(BuildContext context, String? tool) {
    final l10n = context.l10n;
    return switch (tool) {
      'get_schedule' => l10n.toolSchedule,
      'search_documents' => l10n.toolDocuments,
      'university_info' => l10n.toolUniversity,
      'navigate' => l10n.toolNavigate,
      _ => l10n.thinking,
    };
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
    child: Row(
      children: [
        const SizedBox.square(dimension: 14, child: CircularProgressIndicator(strokeWidth: 2)),
        const SizedBox(width: 8),
        Text(text, style: Theme.of(context).textTheme.bodySmall),
      ],
    ),
  );
}

class _VoicePanel extends StatelessWidget {
  const _VoicePanel({required this.voice});

  final VoiceState voice;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final scheme = Theme.of(context).colorScheme;
    final label = switch (voice.status) {
      VoiceStatus.listening => l10n.listening,
      VoiceStatus.connecting || VoiceStatus.thinking => l10n.thinking,
      _ => '',
    };
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.secondaryContainer, borderRadius: BorderRadius.circular(16)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(voice.status == VoiceStatus.speaking ? Icons.volume_up : Icons.mic, color: scheme.onSecondaryContainer),
            const SizedBox(width: 8),
            Text(label, style: TextStyle(color: scheme.onSecondaryContainer)),
          ]),
          if (voice.transcript.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('«${voice.transcript}»', style: const TextStyle(fontStyle: FontStyle.italic)),
          ],
        ],
      ),
    );
  }
}

/// Кнопка микрофона: удерживать (по умолчанию) или нажать для старта и ещё раз для отправки.
class VoiceButton extends ConsumerWidget {
  const VoiceButton({super.key, required this.onStart, required this.onStop});

  final Future<void> Function() onStart;
  final Future<void> Function() onStop;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceControllerProvider);
    final hold = ref.watch(settingsProvider.select((s) => s.holdToTalk));
    final listening = voice.status == VoiceStatus.listening;
    final scheme = Theme.of(context).colorScheme;
    final button = AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      width: listening ? 52 : 44,
      height: listening ? 52 : 44,
      decoration: BoxDecoration(shape: BoxShape.circle, color: listening ? scheme.error : scheme.primaryContainer),
      child: Icon(listening ? Icons.mic : Icons.mic_none, color: listening ? scheme.onError : scheme.onPrimaryContainer),
    );
    final tooltip = hold ? context.l10n.holdToTalk : context.l10n.tapToTalk;
    if (hold) {
      return Tooltip(
        message: tooltip,
        child: GestureDetector(onLongPressStart: (_) => onStart(), onLongPressEnd: (_) => onStop(), child: button),
      );
    }
    return Tooltip(
      message: tooltip,
      child: InkWell(customBorder: const CircleBorder(), onTap: listening ? onStop : onStart, child: button),
    );
  }
}

class MessageBubble extends ConsumerWidget {
  const MessageBubble({super.key, required this.message, required this.chatKey});

  final ChatMessage message;
  final ChatKey chatKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scheme = Theme.of(context).colorScheme;
    final l10n = context.l10n;
    final user = message.isUser;
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * (user ? 0.8 : 0.92)),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
          decoration: BoxDecoration(
            color: user ? scheme.primaryContainer : scheme.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(18),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (message.mode == 'voice')
                Padding(padding: const EdgeInsets.only(bottom: 4), child: Icon(Icons.mic, size: 14, color: scheme.outline)),
              if (user)
                SelectableText(message.content)
              else
                message.content.isEmpty
                    ? const SizedBox(height: 18, width: 36, child: LinearProgressIndicator())
                    : GptMarkdown(message.content, style: Theme.of(context).textTheme.bodyMedium),
              if (message.citations.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(l10n.sources, style: Theme.of(context).textTheme.labelSmall),
                Wrap(
                  spacing: 6,
                  children: [
                    for (final c in message.citations)
                      ActionChip(
                        avatar: CircleAvatar(child: Text('${c.n}', style: const TextStyle(fontSize: 11))),
                        label: Text(c.page == null ? c.title : '${c.title}, ${l10n.pageShort(c.page!)}', overflow: TextOverflow.ellipsis),
                        onPressed: () => showSource(context, ref, c),
                      ),
                  ],
                ),
              ],
              if (!user && message.content.isNotEmpty)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      iconSize: 18,
                      tooltip: l10n.copy,
                      icon: const Icon(Icons.copy_rounded),
                      onPressed: () => Clipboard.setData(ClipboardData(text: message.content)),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      iconSize: 18,
                      tooltip: l10n.speak,
                      icon: const Icon(Icons.volume_up_outlined),
                      onPressed: () => guarded(context, () async {
                        final player = ref.read(_speechPlayerProvider);
                        if (!await player.isAvailable) throw ApiException(l10n.ttsUnavailable);
                        final api = ref.read(apiClientProvider);
                        final audio = await SpeechRepository(api).speak(message.content);
                        await player.setRate(ref.read(settingsProvider).voiceSpeed);
                        player.enqueue(audio);
                      }),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      iconSize: 18,
                      tooltip: l10n.helpful,
                      icon: const Icon(Icons.thumb_up_alt_outlined),
                      onPressed: () => _rate(context, ref, 1),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      iconSize: 18,
                      tooltip: l10n.notHelpful,
                      icon: const Icon(Icons.thumb_down_alt_outlined),
                      onPressed: () => _rate(context, ref, -1),
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _rate(BuildContext context, WidgetRef ref, int rating) async {
    var include = false;
    if (rating < 0) {
      include = await confirm(context, context.l10n.attachDialog, confirmLabel: context.l10n.ok);
    }
    if (!context.mounted) return;
    await guarded(context, () => ref.read(chatControllerProvider(chatKey).notifier).rate(message, rating, includeDialog: include));
    if (context.mounted) showMessage(context, context.l10n.feedbackThanks);
  }
}

Future<void> showSource(BuildContext context, WidgetRef ref, Citation citation) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (ctx) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.6,
      builder: (ctx, scroll) => FutureBuilder<SourceChunk>(
        future: ref.read(documentsRepositoryProvider).chunk(citation.documentId, citation.chunkId),
        builder: (ctx, snap) {
          final chunk = snap.data;
          return ListView(
            controller: scroll,
            padding: const EdgeInsets.all(20),
            children: [
              Text(citation.title, style: Theme.of(ctx).textTheme.titleMedium),
              if (citation.page != null) Text(ctx.l10n.pageShort(citation.page!)),
              if (citation.section != null) Text(citation.section!, style: Theme.of(ctx).textTheme.labelLarge),
              const Divider(),
              if (snap.hasError) Text(errorText(ctx, snap.error!)),
              if (chunk == null && !snap.hasError) const Center(child: CircularProgressIndicator()),
              if (chunk != null) SelectableText(chunk.body),
            ],
          );
        },
      ),
    ),
  );
}
