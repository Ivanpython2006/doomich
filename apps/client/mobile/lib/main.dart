import 'package:doomich_ui/doomich_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// «Думыч» для Android: нижняя навигация, QR-коды приглашения, подтверждение входа на ПК.
void main() => runDoomich(const DoomichMobileApp());

class DoomichMobileApp extends StatelessWidget {
  const DoomichMobileApp({super.key});

  @override
  Widget build(BuildContext context) => DoomichApp(shell: (_) => const MobileShell(), scanQr: scanQrCode);
}

/// Открыть сканер и вернуть содержимое первого распознанного QR-кода.
Future<String?> scanQrCode(BuildContext context) =>
    Navigator.push<String>(context, MaterialPageRoute(builder: (_) => const QrScanPage()));

class QrScanPage extends StatefulWidget {
  const QrScanPage({super.key});

  @override
  State<QrScanPage> createState() => _QrScanPageState();
}

class _QrScanPageState extends State<QrScanPage> {
  final _controller = MobileScannerController(formats: const [BarcodeFormat.qrCode]);
  bool _done = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(context.l10n.scanQr)),
    body: MobileScanner(
      controller: _controller,
      onDetect: (capture) {
        final value = capture.barcodes.firstOrNull?.rawValue;
        if (value == null || _done) return;
        _done = true;
        Navigator.pop(context, value);
      },
    ),
  );
}

class MobileShell extends ConsumerStatefulWidget {
  const MobileShell({super.key});

  @override
  ConsumerState<MobileShell> createState() => _MobileShellState();
}

class _MobileShellState extends ConsumerState<MobileShell> {
  int _tab = 0;

  void _openChat(ChatKey key) => Navigator.push(context, MaterialPageRoute(builder: (_) => ChatView(chatKey: key)));

  Future<void> _approveDesktopLogin() async {
    final raw = await scanQrCode(context);
    if (raw == null || !raw.startsWith('doomich-login:') || !mounted) return;
    final ok = await guarded(context, () async {
      await ref.read(authRepositoryProvider).qrApprove(raw.substring('doomich-login:'.length));
      return true;
    });
    if (ok == true && mounted) showMessage(context, context.l10n.desktopLoginApproved);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final me = ref.watch(sessionProvider).value;
    final lectures = me?.feature('lectures') ?? false;
    final pages = <(NavigationDestination, Widget)>[
      (
        NavigationDestination(icon: const Icon(Icons.chat_bubble_outline), selectedIcon: const Icon(Icons.chat_bubble), label: l10n.navChat),
        Scaffold(appBar: AppBar(title: Text(l10n.appTitle)), body: ChatListView(onOpen: _openChat)),
      ),
      (
        NavigationDestination(icon: const Icon(Icons.calendar_month_outlined), selectedIcon: const Icon(Icons.calendar_month), label: l10n.navSchedule),
        const ScheduleScreen(),
      ),
      (
        NavigationDestination(icon: const Icon(Icons.folder_outlined), selectedIcon: const Icon(Icons.folder), label: l10n.navDocuments),
        DocumentsScreen(onAsk: _openChat),
      ),
      if (lectures)
        (
          NavigationDestination(icon: const Icon(Icons.note_alt_outlined), selectedIcon: const Icon(Icons.note_alt), label: l10n.navLectures),
          LecturesScreen(onAsk: _openChat),
        ),
      (
        NavigationDestination(icon: const Icon(Icons.settings_outlined), selectedIcon: const Icon(Icons.settings), label: l10n.navSettings),
        SettingsScreen(
          extraTiles: [
            ListTile(
              leading: const Icon(Icons.qr_code_scanner),
              title: Text(l10n.approveDesktopLogin),
              onTap: _approveDesktopLogin,
            ),
          ],
        ),
      ),
    ];
    final index = _tab.clamp(0, pages.length - 1);
    return Scaffold(
      body: IndexedStack(index: index, children: [for (final p in pages) p.$2]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: [for (final p in pages) p.$1],
      ),
    );
  }
}
