import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Адрес сервера по умолчанию задаётся при сборке: `--dart-define=DOOMICH_API=https://api.example.ru`.
const String defaultApiBase = String.fromEnvironment('DOOMICH_API', defaultValue: 'http://localhost:8000');

/// Настройки устройства. Хранятся только локально (не персональные данные).
@immutable
class AppSettings {
  const AppSettings({
    this.themeMode = ThemeMode.system,
    this.locale,
    this.apiBase = defaultApiBase,
    this.autoSpeak = true,
    this.voiceSpeed = 1.0,
    this.holdToTalk = true,
    this.teacherName,
  });

  final ThemeMode themeMode;
  final Locale? locale;
  final String apiBase;
  final bool autoSpeak;
  final double voiceSpeed;
  final bool holdToTalk;

  /// Выбор «я — этот преподаватель» хранится только на устройстве: сервер не связывает аккаунт с ФИО.
  final String? teacherName;

  AppSettings copyWith({
    ThemeMode? themeMode,
    Locale? locale,
    bool clearLocale = false,
    String? apiBase,
    bool? autoSpeak,
    double? voiceSpeed,
    bool? holdToTalk,
    String? teacherName,
    bool clearTeacher = false,
  }) => AppSettings(
    themeMode: themeMode ?? this.themeMode,
    locale: clearLocale ? null : (locale ?? this.locale),
    apiBase: apiBase ?? this.apiBase,
    autoSpeak: autoSpeak ?? this.autoSpeak,
    voiceSpeed: voiceSpeed ?? this.voiceSpeed,
    holdToTalk: holdToTalk ?? this.holdToTalk,
    teacherName: clearTeacher ? null : (teacherName ?? this.teacherName),
  );
}

/// SharedPreferences загружаются до запуска приложения и подставляются в ProviderScope.
final sharedPreferencesProvider = Provider<SharedPreferences>(
  (ref) => throw UnimplementedError('Передайте SharedPreferences через overrides в ProviderScope'),
);

class SettingsController extends Notifier<AppSettings> {
  static const _theme = 'theme_mode';
  static const _locale = 'locale';
  static const _api = 'api_base';
  static const _speak = 'auto_speak';
  static const _speed = 'voice_speed';
  static const _hold = 'hold_to_talk';
  static const _teacher = 'teacher_name';

  SharedPreferences get _prefs => ref.read(sharedPreferencesProvider);

  @override
  AppSettings build() {
    final prefs = ref.watch(sharedPreferencesProvider);
    final localeCode = prefs.getString(_locale);
    return AppSettings(
      themeMode: ThemeMode.values.firstWhere((m) => m.name == prefs.getString(_theme), orElse: () => ThemeMode.system),
      locale: localeCode == null ? null : Locale(localeCode),
      apiBase: prefs.getString(_api) ?? defaultApiBase,
      autoSpeak: prefs.getBool(_speak) ?? true,
      voiceSpeed: prefs.getDouble(_speed) ?? 1.0,
      holdToTalk: prefs.getBool(_hold) ?? true,
      teacherName: prefs.getString(_teacher),
    );
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    await _prefs.setString(_theme, mode.name);
    state = state.copyWith(themeMode: mode);
  }

  Future<void> setLocale(Locale? locale) async {
    if (locale == null) {
      await _prefs.remove(_locale);
    } else {
      await _prefs.setString(_locale, locale.languageCode);
    }
    state = state.copyWith(locale: locale, clearLocale: locale == null);
  }

  Future<void> setApiBase(String url) async {
    final normalized = url.trim().replaceAll(RegExp(r'/+$'), '');
    await _prefs.setString(_api, normalized);
    state = state.copyWith(apiBase: normalized);
  }

  Future<void> setAutoSpeak(bool value) async {
    await _prefs.setBool(_speak, value);
    state = state.copyWith(autoSpeak: value);
  }

  Future<void> setVoiceSpeed(double value) async {
    await _prefs.setDouble(_speed, value);
    state = state.copyWith(voiceSpeed: value);
  }

  Future<void> setHoldToTalk(bool value) async {
    await _prefs.setBool(_hold, value);
    state = state.copyWith(holdToTalk: value);
  }

  Future<void> setTeacher(String? name) async {
    if (name == null) {
      await _prefs.remove(_teacher);
    } else {
      await _prefs.setString(_teacher, name);
    }
    state = state.copyWith(teacherName: name, clearTeacher: name == null);
  }
}

final settingsProvider = NotifierProvider<SettingsController, AppSettings>(SettingsController.new);
