import 'package:material_ui/material_ui.dart';
import 'package:cupertino_ui/cupertino_ui.dart' show GlobalCupertinoLocalizations;
import 'package:flutter_localizations/flutter_localizations.dart' show GlobalWidgetsLocalizations;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../l10n/gen/doomich_localizations.dart';
import 'providers.dart';
import 'screens/onboarding.dart';
import 'settings.dart';
import 'theme.dart';
import 'widgets/common.dart';

/// Запуск приложения: настройки читаются до первого кадра, автоповтор ошибок Riverpod отключён
/// (иначе истёкшая сессия повторялась бы бесконечно).
Future<void> runDoomich(Widget app) async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final tokens = await createTokenStore();
  runApp(
    ProviderScope(
      retry: (retryCount, error) => null,
      overrides: [
        sharedPreferencesProvider.overrideWithValue(prefs),
        tokenStoreProvider.overrideWithValue(tokens),
      ],
      child: app,
    ),
  );
}

/// Локализации интерфейса. Material и Cupertino — из пакетов material_ui/cupertino_ui
/// (сгенерированный список DoomichLocalizations.localizationsDelegates ссылается на старый flutter/material).
const doomichLocalizationDelegates = <LocalizationsDelegate<dynamic>>[
  DoomichLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

/// Корневой виджет: тема, язык, онбординг или основной интерфейс платформы.
class DoomichApp extends ConsumerWidget {
  const DoomichApp({super.key, required this.shell, this.scanQr, this.qrLogin});

  /// Интерфейс после входа — у Android и ПК он свой.
  final WidgetBuilder shell;
  final QrScanner? scanQr;
  final QrLoginBuilder? qrLogin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    return MaterialApp(
      onGenerateTitle: (ctx) => ctx.l10n.appTitle,
      debugShowCheckedModeBanner: false,
      theme: DoomichTheme.light(),
      darkTheme: DoomichTheme.dark(),
      themeMode: settings.themeMode,
      locale: settings.locale,
      supportedLocales: DoomichLocalizations.supportedLocales,
      localizationsDelegates: doomichLocalizationDelegates,
      home: _AuthGate(shell: shell, scanQr: scanQr, qrLogin: qrLogin),
    );
  }
}

class _AuthGate extends ConsumerWidget {
  const _AuthGate({required this.shell, this.scanQr, this.qrLogin});

  final WidgetBuilder shell;
  final QrScanner? scanQr;
  final QrLoginBuilder? qrLogin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    return session.when(
      data: (me) => me == null ? OnboardingFlow(scanQr: scanQr, qrLogin: qrLogin) : shell(context),
      loading: () => const Scaffold(body: Center(child: CircularProgressIndicator())),
      error: (e, _) => Scaffold(
        body: AsyncView<void>(value: AsyncError(e, StackTrace.current), builder: (_) => const SizedBox(), onRetry: () => ref.invalidate(sessionProvider)),
      ),
    );
  }
}
