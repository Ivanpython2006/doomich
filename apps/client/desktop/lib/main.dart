import 'dart:async';

import 'package:doomich_core/doomich_core.dart';
import 'package:doomich_ui/doomich_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:qr_flutter/qr_flutter.dart';

/// «Думыч» для Windows и Linux: боковая навигация, две панели, горячие клавиши, вход по QR с телефона.
void main() => runDoomich(const DoomichDesktopApp());

class DoomichDesktopApp extends StatelessWidget {
  const DoomichDesktopApp({super.key});

  @override
  Widget build(BuildContext context) =>
      DoomichApp(shell: (_) => const DesktopShell(), qrLogin: (_) => const QrLoginScreen());
}

class DesktopShell extends ConsumerStatefulWidget {
  const DesktopShell({super.key});

  @override
  ConsumerState<DesktopShell> createState() => _DesktopShellState();
}

class _DesktopShellState extends ConsumerState<DesktopShell> {
  int _section = 0;
  ChatKey? _chat;
  final _chatView = GlobalKey<ChatViewState>();
  bool _voiceKeyDown = false;

  void _openChat(ChatKey key) => setState(() {
    _section = 0;
    _chat = key;
  });

  Future<void> _newChat() async {
    final chat = await guarded(context, () => ref.read(chatListProvider.notifier).create());
    if (chat != null) _openChat(ChatKey.server(chat.id));
  }

  /// Ctrl+Пробел: удерживать — говорить, отпустить — отправить.
  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event.logicalKey != LogicalKeyboardKey.space) return KeyEventResult.ignored;
    final view = _chatView.currentState;
    if (event is KeyDownEvent && HardwareKeyboard.instance.isControlPressed && !_voiceKeyDown && view != null) {
      _voiceKeyDown = true;
      unawaited(view.startVoice());
      return KeyEventResult.handled;
    }
    if (event is KeyUpEvent && _voiceKeyDown) {
      _voiceKeyDown = false;
      unawaited(view?.stopVoice());
      return KeyEventResult.handled;
    }
    return _voiceKeyDown ? KeyEventResult.handled : KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final me = ref.watch(sessionProvider).value;
    final lectures = me?.feature('lectures') ?? false;
    final sections = <(NavigationRailDestination, Widget)>[
      (
        NavigationRailDestination(icon: const Icon(Icons.chat_bubble_outline), selectedIcon: const Icon(Icons.chat_bubble), label: Text(l10n.navChat)),
        Row(
          children: [
            SizedBox(width: 300, child: ChatListView(onOpen: _openChat, selected: _chat)),
            const VerticalDivider(width: 1),
            Expanded(
              child: _chat == null
                  ? EmptyState(icon: Icons.psychology_alt_outlined, text: '${l10n.emptyChatHint}\n\n${l10n.shortcutsHint}')
                  : Scaffold(
                      appBar: AppBar(
                        title: Text(_chat!.isIncognito ? l10n.incognito : l10n.navChat),
                        automaticallyImplyLeading: false,
                      ),
                      body: ChatView(key: _chatView, chatKey: _chat!, showAppBar: false),
                    ),
            ),
          ],
        ),
      ),
      (
        NavigationRailDestination(icon: const Icon(Icons.calendar_month_outlined), selectedIcon: const Icon(Icons.calendar_month), label: Text(l10n.navSchedule)),
        const ScheduleScreen(),
      ),
      (
        NavigationRailDestination(icon: const Icon(Icons.folder_outlined), selectedIcon: const Icon(Icons.folder), label: Text(l10n.navDocuments)),
        DocumentsScreen(onAsk: _openChat),
      ),
      if (lectures)
        (
          NavigationRailDestination(icon: const Icon(Icons.note_alt_outlined), selectedIcon: const Icon(Icons.note_alt), label: Text(l10n.navLectures)),
          LecturesScreen(onAsk: _openChat),
        ),
      (
        NavigationRailDestination(icon: const Icon(Icons.settings_outlined), selectedIcon: const Icon(Icons.settings), label: Text(l10n.navSettings)),
        const SettingsScreen(),
      ),
    ];
    final index = _section.clamp(0, sections.length - 1);
    return CallbackShortcuts(
      bindings: {const SingleActivator(LogicalKeyboardKey.keyN, control: true): _newChat},
      child: Focus(
        autofocus: true,
        onKeyEvent: _onKey,
        child: Scaffold(
          body: Row(
            children: [
              NavigationRail(
                selectedIndex: index,
                labelType: NavigationRailLabelType.all,
                leading: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Icon(Icons.psychology_alt_rounded, size: 36, color: Theme.of(context).colorScheme.primary),
                ),
                onDestinationSelected: (i) => setState(() => _section = i),
                destinations: [for (final s in sections) s.$1],
              ),
              const VerticalDivider(width: 1),
              Expanded(child: IndexedStack(index: index, children: [for (final s in sections) s.$2])),
            ],
          ),
        ),
      ),
    );
  }
}

/// Вход на ПК: компьютер показывает QR, телефон с «Думычем» подтверждает вход — пароль на ПК не вводится.
class QrLoginScreen extends ConsumerStatefulWidget {
  const QrLoginScreen({super.key});

  @override
  ConsumerState<QrLoginScreen> createState() => _QrLoginScreenState();
}

class _QrLoginScreenState extends ConsumerState<QrLoginScreen> {
  ({String challengeId, String secret})? _challenge;
  Timer? _poll;
  Timer? _renew;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _renew?.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    final repo = ref.read(authRepositoryProvider);
    final challenge = await guarded(context, repo.qrStart);
    if (challenge == null || !mounted) return;
    setState(() => _challenge = challenge);
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) async {
      try {
        final result = await repo.qrPoll(challenge.challengeId, challenge.secret);
        if (result != null && mounted) {
          _poll?.cancel();
          Navigator.of(context).popUntil((r) => r.isFirst);
          ref.read(sessionProvider.notifier).signedIn(result.user);
        }
      } on ApiException {
        // код устарел — выпустим новый
      }
    });
    _renew?.cancel();
    _renew = Timer(const Duration(minutes: 2, seconds: 50), _start);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final challenge = _challenge;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.qrDesktopLogin)),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (challenge == null)
                const CircularProgressIndicator()
              else
                Container(
                  color: Colors.white,
                  padding: const EdgeInsets.all(16),
                  child: QrImageView(data: 'doomich-login:${challenge.secret}', size: 260),
                ),
              const SizedBox(height: 24),
              Text(l10n.qrDesktopHint, textAlign: TextAlign.center),
            ],
          ),
        ),
      ),
    );
  }
}
