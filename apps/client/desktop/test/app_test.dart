import 'package:doomich_core/doomich_core.dart';
import 'package:doomich_desktop/main.dart';
import 'package:doomich_ui/doomich_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('без сессии открывается онбординг', (tester) async {
    SharedPreferences.setMockInitialValues({'locale': 'ru'});
    final prefs = await SharedPreferences.getInstance();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sharedPreferencesProvider.overrideWithValue(prefs),
          tokenStoreProvider.overrideWithValue(MemoryTokenStore()),
        ],
        child: const DoomichDesktopApp(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Привет! Я Думыч'), findsOneWidget);
    expect(find.text('Войти по QR с телефона'), findsOneWidget);
  });
}
