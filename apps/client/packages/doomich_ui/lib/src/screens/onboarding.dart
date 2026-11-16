import 'dart:async';
import 'dart:convert';

import 'package:doomich_core/doomich_core.dart';
import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import '../settings.dart';
import '../widgets/common.dart';

/// Сканер QR-кода (только в мобильном приложении). Возвращает строку из QR или null.
typedef QrScanner = Future<String?> Function(BuildContext context);

/// Экран входа по QR для ПК (только в десктопном приложении).
typedef QrLoginBuilder = Widget Function(BuildContext context);

/// Онбординг без персональных данных: язык и тема → код приглашения → псевдоним и пароль → код восстановления.
class OnboardingFlow extends StatelessWidget {
  const OnboardingFlow({super.key, this.scanQr, this.qrLogin});

  final QrScanner? scanQr;
  final QrLoginBuilder? qrLogin;

  @override
  Widget build(BuildContext context) => WelcomeScreen(scanQr: scanQr, qrLogin: qrLogin);
}

class _Narrow extends StatelessWidget {
  const _Narrow({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 460), child: child),
    ),
  );
}

class WelcomeScreen extends ConsumerWidget {
  const WelcomeScreen({super.key, this.scanQr, this.qrLogin});

  final QrScanner? scanQr;
  final QrLoginBuilder? qrLogin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final settings = ref.watch(settingsProvider);
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(actions: [
        IconButton(
          tooltip: l10n.serverAddress,
          icon: const Icon(Icons.dns_outlined),
          onPressed: () => showServerDialog(context, ref),
        ),
      ]),
      body: _Narrow(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Icon(Icons.psychology_alt_rounded, size: 88, color: theme.colorScheme.primary),
            const SizedBox(height: 16),
            Text(l10n.welcomeTitle, style: theme.textTheme.headlineMedium, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            Text(l10n.welcomeSubtitle, style: theme.textTheme.bodyLarge, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(l10n.welcomePrivacy, style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.primary),
                textAlign: TextAlign.center),
            const SizedBox(height: 24),
            SegmentedButton<String>(
              segments: const [ButtonSegment(value: 'ru', label: Text('Русский')), ButtonSegment(value: 'en', label: Text('English'))],
              selected: {settings.locale?.languageCode ?? Localizations.localeOf(context).languageCode},
              onSelectionChanged: (v) => ref.read(settingsProvider.notifier).setLocale(Locale(v.first)),
            ),
            const SizedBox(height: 12),
            SegmentedButton<ThemeMode>(
              segments: [
                ButtonSegment(value: ThemeMode.system, label: Text(l10n.themeSystem)),
                ButtonSegment(value: ThemeMode.light, label: Text(l10n.themeLight)),
                ButtonSegment(value: ThemeMode.dark, label: Text(l10n.themeDark)),
              ],
              selected: {settings.themeMode},
              onSelectionChanged: (v) => ref.read(settingsProvider.notifier).setThemeMode(v.first),
            ),
            const SizedBox(height: 32),
            FilledButton(
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => InviteScreen(scanQr: scanQr))),
              child: Text(l10n.start),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const LoginScreen())),
              child: Text(l10n.haveAccount),
            ),
            if (qrLogin != null) ...[
              const SizedBox(height: 8),
              TextButton.icon(
                icon: const Icon(Icons.qr_code_2),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: qrLogin!)),
                label: Text(l10n.qrDesktopLogin),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

Future<void> showServerDialog(BuildContext context, WidgetRef ref) async {
  final l10n = context.l10n;
  final value = await promptText(
    context,
    title: l10n.serverAddress,
    initial: ref.read(settingsProvider).apiBase,
    label: l10n.serverAddressHelp,
  );
  if (value != null && Uri.tryParse(value.trim())?.hasScheme == true) {
    await ref.read(settingsProvider.notifier).setApiBase(value);
  }
}

class InviteScreen extends ConsumerStatefulWidget {
  const InviteScreen({super.key, this.scanQr, this.initialCode});

  final QrScanner? scanQr;
  final String? initialCode;

  @override
  ConsumerState<InviteScreen> createState() => _InviteScreenState();
}

class _InviteScreenState extends ConsumerState<InviteScreen> {
  late final _code = TextEditingController(text: widget.initialCode);
  InviteInfo? _info;
  bool _checking = false;
  String? _error;

  Future<void> _check() async {
    final code = _code.text.trim();
    if (code.length < 8) return;
    setState(() => _checking = true);
    try {
      final info = await ref.read(authRepositoryProvider).checkInvite(code);
      setState(() {
        _info = info;
        _error = info.valid ? null : context.l10n.inviteInvalid;
      });
    } catch (e) {
      setState(() => _error = errorText(context, e));
    } finally {
      if (mounted) setState(() => _checking = false);
    }
  }

  Future<void> _scan() async {
    final raw = await widget.scanQr!(context);
    final code = raw == null ? null : inviteCodeFromQr(raw);
    if (code != null) {
      _code.text = code;
      await _check();
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final info = _info;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.inviteTitle)),
      body: _Narrow(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(l10n.inviteHelp),
            const SizedBox(height: 16),
            TextField(
              controller: _code,
              textCapitalization: TextCapitalization.characters,
              autofocus: true,
              style: const TextStyle(fontSize: 22, letterSpacing: 3, fontFamily: 'monospace'),
              decoration: InputDecoration(hintText: 'XXXX-XXXX', errorText: _error),
              onChanged: (_) => setState(() => _info = null),
              onSubmitted: (_) => _check(),
            ),
            if (widget.scanQr != null) ...[
              const SizedBox(height: 8),
              OutlinedButton.icon(onPressed: _scan, icon: const Icon(Icons.qr_code_scanner), label: Text(l10n.scanQr)),
            ],
            if (info != null && info.valid) ...[
              const SizedBox(height: 16),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.school_outlined),
                  title: Text(l10n.inviteJoining(info.university ?? '')),
                  subtitle: Text([
                    info.role == 'teacher' ? l10n.roleTeacher : l10n.roleStudent,
                    if (info.group != null) l10n.groupLabel(info.group!),
                  ].join(' · ')),
                ),
              ),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _checking
                  ? null
                  : () async {
                      if (info?.valid != true) await _check();
                      if (!context.mounted || _info?.valid != true) return;
                      await Navigator.push(
                        context,
                        MaterialPageRoute(builder: (_) => CreateAccountScreen(inviteCode: _code.text.trim())),
                      );
                    },
              child: _checking ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2)) : Text(l10n.next),
            ),
          ],
        ),
      ),
    );
  }
}

class CreateAccountScreen extends ConsumerStatefulWidget {
  const CreateAccountScreen({super.key, required this.inviteCode});

  final String inviteCode;

  @override
  ConsumerState<CreateAccountScreen> createState() => _CreateAccountScreenState();
}

class _CreateAccountScreenState extends ConsumerState<CreateAccountScreen> {
  final _login = TextEditingController();
  final _password = TextEditingController();
  List<String> _suggestions = const [];
  LoginCheck? _check;
  Timer? _debounce;
  bool _agree = false;
  bool _busy = false;
  bool _obscure = true;

  @override
  void initState() {
    super.initState();
    _suggestions = Pseudonyms.suggest(ref.read(settingsProvider).locale?.languageCode ?? 'ru');
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _onLoginChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () async {
      if (value.trim().length < 3) return;
      try {
        final check = await ref.read(authRepositoryProvider).checkLogin(value.trim());
        if (mounted) setState(() => _check = check);
      } catch (_) {}
    });
    setState(() => _check = null);
  }

  Future<void> _submit() async {
    setState(() => _busy = true);
    final locale = ref.read(settingsProvider).locale?.languageCode ?? Localizations.localeOf(context).languageCode;
    try {
      final result = await ref.read(authRepositoryProvider).register(
        inviteCode: widget.inviteCode,
        login: _login.text.trim(),
        password: _password.text,
        locale: locale == 'en' ? 'en' : 'ru',
      );
      if (!mounted) return;
      await Navigator.pushAndRemoveUntil(
        context,
        MaterialPageRoute(builder: (_) => RecoveryCodeScreen(code: result.recoveryCode!, me: result.user)),
        (route) => route.isFirst,
      );
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final strength = passwordStrength(_password.text);
    final login = _login.text.trim();
    final nameWarning = login.isNotEmpty && looksLikeRealName(login);
    final ready = login.length >= 3 && _password.text.length >= 10 && _agree && (_check?.available ?? true);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.accountTitle)),
      body: _Narrow(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _login,
              decoration: InputDecoration(
                labelText: l10n.pseudonymLabel,
                helperText: l10n.pseudonymHelp,
                helperMaxLines: 2,
                errorText: _check != null && !_check!.available
                    ? l10n.pseudonymTaken
                    : (_check?.problem),
              ),
              onChanged: _onLoginChanged,
            ),
            if (nameWarning)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(l10n.pseudonymLooksLikeName, style: TextStyle(color: Theme.of(context).colorScheme.tertiary)),
              ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text('${l10n.suggestions}:'),
                for (final s in _suggestions)
                  ActionChip(
                    label: Text(s),
                    onPressed: () {
                      _login.text = s;
                      _onLoginChanged(s);
                    },
                  ),
              ],
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _password,
              obscureText: _obscure,
              decoration: InputDecoration(
                labelText: l10n.passwordLabel,
                helperText: l10n.passwordHelp,
                suffixIcon: IconButton(
                  icon: Icon(_obscure ? Icons.visibility : Icons.visibility_off),
                  onPressed: () => setState(() => _obscure = !_obscure),
                ),
              ),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 8),
            LinearProgressIndicator(value: (strength + 1) / 5, minHeight: 6, borderRadius: BorderRadius.circular(3)),
            const SizedBox(height: 4),
            Text(strength <= 1 ? l10n.passwordWeak : (strength <= 2 ? l10n.passwordMedium : l10n.passwordStrong)),
            const SizedBox(height: 16),
            CheckboxListTile(
              value: _agree,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              onChanged: (v) => setState(() => _agree = v ?? false),
              title: Text(l10n.agreeTerms),
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: ready && !_busy ? _submit : null, child: Text(l10n.createAccount)),
          ],
        ),
      ),
    );
  }
}

class RecoveryCodeScreen extends ConsumerStatefulWidget {
  const RecoveryCodeScreen({super.key, required this.code, required this.me, this.title});

  final String code;
  final Me me;
  final String? title;

  @override
  ConsumerState<RecoveryCodeScreen> createState() => _RecoveryCodeScreenState();
}

class _RecoveryCodeScreenState extends ConsumerState<RecoveryCodeScreen> {
  bool _saved = false;

  Future<void> _saveFile() async {
    final text = 'Думыч — код восстановления\nПсевдоним: ${widget.me.login}\nКод: ${widget.code}\n';
    final uri = await FilePicker.saveFile(
      fileName: 'doomich-recovery-code.txt',
      bytes: utf8.encode(text),
      mimeType: 'text/plain',
    );
    if (uri != null && mounted) showMessage(context, context.l10n.savedTo(uri.scheme == 'file' ? uri.toFilePath() : uri.toString()));
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(title: Text(widget.title ?? l10n.recoveryTitle), automaticallyImplyLeading: false),
        body: _Narrow(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Icon(Icons.key_rounded, size: 56, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 16),
              Text(l10n.recoveryText, textAlign: TextAlign.center),
              const SizedBox(height: 20),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: SelectableText(
                    widget.code,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 22, letterSpacing: 2, fontFamily: 'monospace'),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.copy),
                      label: Text(l10n.copy),
                      onPressed: () async {
                        await Clipboard.setData(ClipboardData(text: widget.code));
                        if (context.mounted) showMessage(context, l10n.copied);
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(icon: const Icon(Icons.save_alt), label: Text(l10n.saveToFile), onPressed: _saveFile),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              CheckboxListTile(
                value: _saved,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                onChanged: (v) => setState(() => _saved = v ?? false),
                title: Text(l10n.recoverySaved),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: _saved
                    ? () {
                        Navigator.of(context).popUntil((r) => r.isFirst);
                        ref.read(sessionProvider.notifier).signedIn(widget.me);
                      }
                    : null,
                child: Text(l10n.next),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _login = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      await ref.read(sessionProvider.notifier).login(_login.text.trim(), _password.text);
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.loginTitle)),
      body: _Narrow(
        child: AutofillGroup(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextField(
                controller: _login,
                autofillHints: const [AutofillHints.username],
                decoration: InputDecoration(labelText: l10n.pseudonymLabel),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _password,
                obscureText: true,
                autofillHints: const [AutofillHints.password],
                decoration: InputDecoration(labelText: l10n.passwordLabel),
                onSubmitted: (_) => _submit(),
              ),
              const SizedBox(height: 20),
              FilledButton(onPressed: _busy ? null : _submit, child: Text(l10n.login)),
              TextButton(
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const RecoverScreen())),
                child: Text(l10n.forgotPassword),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class RecoverScreen extends ConsumerStatefulWidget {
  const RecoverScreen({super.key});

  @override
  ConsumerState<RecoverScreen> createState() => _RecoverScreenState();
}

class _RecoverScreenState extends ConsumerState<RecoverScreen> {
  final _login = TextEditingController();
  final _code = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      final result = await ref.read(authRepositoryProvider).recover(
        login: _login.text.trim(),
        recoveryCode: _code.text.trim(),
        newPassword: _password.text,
      );
      if (!mounted) return;
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => RecoveryCodeScreen(code: result.recoveryCode!, me: result.user, title: context.l10n.newRecoveryCode),
        ),
      );
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.recoverTitle)),
      body: _Narrow(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _login, decoration: InputDecoration(labelText: l10n.pseudonymLabel)),
            const SizedBox(height: 12),
            TextField(
              controller: _code,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(labelText: l10n.recoveryCodeLabel, hintText: 'XXXX-XXXX-XXXX-XXXX-XXXX'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _password,
              obscureText: true,
              decoration: InputDecoration(labelText: l10n.newPasswordLabel, helperText: l10n.passwordHelp),
            ),
            const SizedBox(height: 20),
            FilledButton(onPressed: _busy ? null : _submit, child: Text(l10n.recover)),
          ],
        ),
      ),
    );
  }
}
