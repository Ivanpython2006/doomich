import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import '../settings.dart';
import '../widgets/common.dart';
import 'onboarding.dart';
import 'schedule.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key, this.extraTiles = const []});

  /// Платформенные пункты (например, «Войти на компьютере» в мобильном приложении).
  final List<Widget> extraTiles;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final settings = ref.watch(settingsProvider);
    final me = ref.watch(sessionProvider).value;
    final controller = ref.read(settingsProvider.notifier);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.navSettings)),
      body: ListView(
        children: [
          if (me != null) ...[
            _Header(l10n.account),
            ListTile(
              leading: const Icon(Icons.account_circle_outlined),
              title: Text(l10n.signedInAs(me.login)),
              subtitle: Text('${me.university.name}${me.group != null ? ' · ${l10n.groupLabel(me.group!.code)}' : ''}'),
            ),
            ListTile(
              leading: const Icon(Icons.groups_outlined),
              title: Text(l10n.chooseGroup),
              subtitle: Text(me.group?.code ?? l10n.noGroup),
              onTap: () => pickGroup(context, ref),
            ),
            ...extraTiles,
          ],
          _Header(l10n.appearance),
          ListTile(
            leading: const Icon(Icons.language),
            title: Text(l10n.language),
            trailing: DropdownButton<String>(
              value: settings.locale?.languageCode ?? 'system',
              underline: const SizedBox.shrink(),
              items: [
                DropdownMenuItem(value: 'system', child: Text(l10n.themeSystem)),
                const DropdownMenuItem(value: 'ru', child: Text('Русский')),
                const DropdownMenuItem(value: 'en', child: Text('English')),
              ],
              onChanged: (v) async {
                await controller.setLocale(v == null || v == 'system' ? null : Locale(v));
                if (v == 'ru' || v == 'en') {
                  // язык ответов по умолчанию тоже меняем на сервере
                  await ref.read(sessionProvider.notifier).updateMe(locale: v).catchError((_) {});
                }
              },
            ),
          ),
          ListTile(
            leading: const Icon(Icons.brightness_6_outlined),
            title: Text(l10n.theme),
            trailing: DropdownButton<ThemeMode>(
              value: settings.themeMode,
              underline: const SizedBox.shrink(),
              items: [
                DropdownMenuItem(value: ThemeMode.system, child: Text(l10n.themeSystem)),
                DropdownMenuItem(value: ThemeMode.light, child: Text(l10n.themeLight)),
                DropdownMenuItem(value: ThemeMode.dark, child: Text(l10n.themeDark)),
              ],
              onChanged: (v) => controller.setThemeMode(v ?? ThemeMode.system),
            ),
          ),
          _Header(l10n.voiceSection),
          SwitchListTile(
            secondary: const Icon(Icons.record_voice_over_outlined),
            title: Text(l10n.autoSpeak),
            value: settings.autoSpeak,
            onChanged: controller.setAutoSpeak,
          ),
          SwitchListTile(
            secondary: const Icon(Icons.touch_app_outlined),
            title: Text(l10n.pushToTalkMode),
            value: settings.holdToTalk,
            onChanged: controller.setHoldToTalk,
          ),
          ListTile(
            leading: const Icon(Icons.speed),
            title: Text(l10n.voiceSpeed),
            trailing: Text('×${settings.voiceSpeed.toStringAsFixed(2)}'),
            subtitle: Slider(
              value: settings.voiceSpeed,
              min: 0.75,
              max: 1.5,
              divisions: 6,
              label: '×${settings.voiceSpeed.toStringAsFixed(2)}',
              onChanged: controller.setVoiceSpeed,
            ),
          ),
          if (me != null) ...[
            _Header(l10n.privacy),
            ListTile(
              leading: const Icon(Icons.history),
              title: Text(l10n.historyRetention),
              trailing: DropdownButton<int>(
                value: me.historyDays,
                underline: const SizedBox.shrink(),
                items: [for (final d in const [1, 7, 30, 90]) DropdownMenuItem(value: d, child: Text(l10n.daysCount(d)))],
                onChanged: (v) => guarded(context, () => ref.read(sessionProvider.notifier).updateMe(historyDays: v)),
              ),
            ),
            ListTile(leading: const Icon(Icons.shield_outlined), title: Text(l10n.privacyNote)),
            ListTile(
              leading: const Icon(Icons.password),
              title: Text(l10n.changePassword),
              onTap: () => _changePassword(context, ref),
            ),
            ListTile(
              leading: const Icon(Icons.delete_sweep_outlined),
              title: Text(l10n.deleteMyData),
              onTap: () async {
                if (await confirm(context, l10n.deleteMyDataConfirm, danger: true) && context.mounted) {
                  await guarded(context, () async {
                    await ref.read(authRepositoryProvider).deleteMyData();
                    ref
                      ..invalidate(chatListProvider)
                      ..invalidate(documentsProvider)
                      ..invalidate(lecturesProvider);
                  });
                }
              },
            ),
            ListTile(
              leading: Icon(Icons.person_remove_outlined, color: Theme.of(context).colorScheme.error),
              title: Text(l10n.deleteAccount, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              onTap: () async {
                final password = await promptText(context, title: l10n.deleteAccountConfirm, label: l10n.passwordLabel, obscure: true);
                if (password != null && password.isNotEmpty && context.mounted) {
                  await guarded(context, () => ref.read(sessionProvider.notifier).deleteAccount(password));
                }
              },
            ),
          ],
          _Header(l10n.about),
          ListTile(
            leading: const Icon(Icons.dns_outlined),
            title: Text(l10n.serverAddress),
            subtitle: Text(settings.apiBase),
            onTap: () => showServerDialog(context, ref),
          ),
          if (me != null)
            ListTile(
              leading: const Icon(Icons.logout),
              title: Text(l10n.logout),
              onTap: () => guarded(context, () => ref.read(sessionProvider.notifier).logout()),
            ),
          ListTile(title: Text(l10n.version('0.1.0'), style: Theme.of(context).textTheme.bodySmall)),
        ],
      ),
    );
  }

  Future<void> _changePassword(BuildContext context, WidgetRef ref) async {
    final l10n = context.l10n;
    final old = await promptText(context, title: l10n.changePassword, label: l10n.currentPassword, obscure: true);
    if (old == null || !context.mounted) return;
    final fresh = await promptText(context, title: l10n.changePassword, label: l10n.newPasswordLabel, obscure: true);
    if (fresh == null || !context.mounted) return;
    final ok = await guarded(context, () async {
      await ref.read(authRepositoryProvider).changePassword(old, fresh);
      return true;
    });
    if (ok == true && context.mounted) showMessage(context, l10n.passwordChanged);
  }
}

class _Header extends StatelessWidget {
  const _Header(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 20, 16, 4),
    child: Text(text, style: Theme.of(context).textTheme.labelLarge?.copyWith(color: Theme.of(context).colorScheme.primary)),
  );
}
