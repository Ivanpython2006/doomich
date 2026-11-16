import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'doomich_localizations_en.dart';
import 'doomich_localizations_ru.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of DoomichLocalizations
/// returned by `DoomichLocalizations.of(context)`.
///
/// Applications need to include `DoomichLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'gen/doomich_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: DoomichLocalizations.localizationsDelegates,
///   supportedLocales: DoomichLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the DoomichLocalizations.supportedLocales
/// property.
abstract class DoomichLocalizations {
  DoomichLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static DoomichLocalizations of(BuildContext context) {
    return Localizations.of<DoomichLocalizations>(
      context,
      DoomichLocalizations,
    )!;
  }

  static const LocalizationsDelegate<DoomichLocalizations> delegate =
      _DoomichLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('ru'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In ru, this message translates to:
  /// **'Думыч'**
  String get appTitle;

  /// No description provided for @ok.
  ///
  /// In ru, this message translates to:
  /// **'ОК'**
  String get ok;

  /// No description provided for @cancel.
  ///
  /// In ru, this message translates to:
  /// **'Отмена'**
  String get cancel;

  /// No description provided for @save.
  ///
  /// In ru, this message translates to:
  /// **'Сохранить'**
  String get save;

  /// No description provided for @delete.
  ///
  /// In ru, this message translates to:
  /// **'Удалить'**
  String get delete;

  /// No description provided for @retry.
  ///
  /// In ru, this message translates to:
  /// **'Повторить'**
  String get retry;

  /// No description provided for @close.
  ///
  /// In ru, this message translates to:
  /// **'Закрыть'**
  String get close;

  /// No description provided for @next.
  ///
  /// In ru, this message translates to:
  /// **'Далее'**
  String get next;

  /// No description provided for @back.
  ///
  /// In ru, this message translates to:
  /// **'Назад'**
  String get back;

  /// No description provided for @copy.
  ///
  /// In ru, this message translates to:
  /// **'Скопировать'**
  String get copy;

  /// No description provided for @copied.
  ///
  /// In ru, this message translates to:
  /// **'Скопировано'**
  String get copied;

  /// No description provided for @loading.
  ///
  /// In ru, this message translates to:
  /// **'Загрузка…'**
  String get loading;

  /// No description provided for @errorGeneric.
  ///
  /// In ru, this message translates to:
  /// **'Что-то пошло не так'**
  String get errorGeneric;

  /// No description provided for @offlineBadge.
  ///
  /// In ru, this message translates to:
  /// **'Нет сети — сохранённая копия от {time}'**
  String offlineBadge(String time);

  /// No description provided for @welcomeTitle.
  ///
  /// In ru, this message translates to:
  /// **'Привет! Я Думыч'**
  String get welcomeTitle;

  /// No description provided for @welcomeSubtitle.
  ///
  /// In ru, this message translates to:
  /// **'ИИ-помощник для учёбы: отвечаю на вопросы текстом и голосом, знаю расписание и читаю ваши документы.'**
  String get welcomeSubtitle;

  /// No description provided for @welcomePrivacy.
  ///
  /// In ru, this message translates to:
  /// **'Без телефона, почты и имени — только псевдоним.'**
  String get welcomePrivacy;

  /// No description provided for @language.
  ///
  /// In ru, this message translates to:
  /// **'Язык'**
  String get language;

  /// No description provided for @theme.
  ///
  /// In ru, this message translates to:
  /// **'Тема'**
  String get theme;

  /// No description provided for @themeSystem.
  ///
  /// In ru, this message translates to:
  /// **'Как в системе'**
  String get themeSystem;

  /// No description provided for @themeLight.
  ///
  /// In ru, this message translates to:
  /// **'Светлая'**
  String get themeLight;

  /// No description provided for @themeDark.
  ///
  /// In ru, this message translates to:
  /// **'Тёмная'**
  String get themeDark;

  /// No description provided for @start.
  ///
  /// In ru, this message translates to:
  /// **'Начать'**
  String get start;

  /// No description provided for @haveAccount.
  ///
  /// In ru, this message translates to:
  /// **'У меня уже есть аккаунт'**
  String get haveAccount;

  /// No description provided for @inviteTitle.
  ///
  /// In ru, this message translates to:
  /// **'Код приглашения'**
  String get inviteTitle;

  /// No description provided for @inviteHelp.
  ///
  /// In ru, this message translates to:
  /// **'Код выдаёт вуз или куратор группы. Можно отсканировать QR-код.'**
  String get inviteHelp;

  /// No description provided for @scanQr.
  ///
  /// In ru, this message translates to:
  /// **'Сканировать QR'**
  String get scanQr;

  /// No description provided for @inviteInvalid.
  ///
  /// In ru, this message translates to:
  /// **'Код недействителен или уже использован'**
  String get inviteInvalid;

  /// No description provided for @inviteJoining.
  ///
  /// In ru, this message translates to:
  /// **'Вы присоединяетесь к «{university}»'**
  String inviteJoining(String university);

  /// No description provided for @roleStudent.
  ///
  /// In ru, this message translates to:
  /// **'студент'**
  String get roleStudent;

  /// No description provided for @roleTeacher.
  ///
  /// In ru, this message translates to:
  /// **'преподаватель'**
  String get roleTeacher;

  /// No description provided for @groupLabel.
  ///
  /// In ru, this message translates to:
  /// **'Группа {group}'**
  String groupLabel(String group);

  /// No description provided for @accountTitle.
  ///
  /// In ru, this message translates to:
  /// **'Создайте аккаунт'**
  String get accountTitle;

  /// No description provided for @pseudonymLabel.
  ///
  /// In ru, this message translates to:
  /// **'Псевдоним'**
  String get pseudonymLabel;

  /// No description provided for @pseudonymHelp.
  ///
  /// In ru, this message translates to:
  /// **'Не используйте настоящее имя — так мы не храним персональные данные.'**
  String get pseudonymHelp;

  /// No description provided for @pseudonymLooksLikeName.
  ///
  /// In ru, this message translates to:
  /// **'Похоже на настоящее имя. Лучше выберите псевдоним.'**
  String get pseudonymLooksLikeName;

  /// No description provided for @pseudonymTaken.
  ///
  /// In ru, this message translates to:
  /// **'Этот псевдоним уже занят'**
  String get pseudonymTaken;

  /// No description provided for @suggestions.
  ///
  /// In ru, this message translates to:
  /// **'Варианты'**
  String get suggestions;

  /// No description provided for @passwordLabel.
  ///
  /// In ru, this message translates to:
  /// **'Пароль'**
  String get passwordLabel;

  /// No description provided for @passwordHelp.
  ///
  /// In ru, this message translates to:
  /// **'Не короче 10 символов'**
  String get passwordHelp;

  /// No description provided for @passwordWeak.
  ///
  /// In ru, this message translates to:
  /// **'Слабый пароль'**
  String get passwordWeak;

  /// No description provided for @passwordMedium.
  ///
  /// In ru, this message translates to:
  /// **'Средний пароль'**
  String get passwordMedium;

  /// No description provided for @passwordStrong.
  ///
  /// In ru, this message translates to:
  /// **'Надёжный пароль'**
  String get passwordStrong;

  /// No description provided for @agreeTerms.
  ///
  /// In ru, this message translates to:
  /// **'Я принимаю пользовательское соглашение и правила обработки данных'**
  String get agreeTerms;

  /// No description provided for @createAccount.
  ///
  /// In ru, this message translates to:
  /// **'Создать аккаунт'**
  String get createAccount;

  /// No description provided for @recoveryTitle.
  ///
  /// In ru, this message translates to:
  /// **'Код восстановления'**
  String get recoveryTitle;

  /// No description provided for @recoveryText.
  ///
  /// In ru, this message translates to:
  /// **'Это единственный способ вернуть доступ: у нас нет вашей почты и телефона. Сохраните код в надёжном месте.'**
  String get recoveryText;

  /// No description provided for @recoverySaved.
  ///
  /// In ru, this message translates to:
  /// **'Я сохранил код'**
  String get recoverySaved;

  /// No description provided for @saveToFile.
  ///
  /// In ru, this message translates to:
  /// **'Сохранить в файл'**
  String get saveToFile;

  /// No description provided for @loginTitle.
  ///
  /// In ru, this message translates to:
  /// **'Вход'**
  String get loginTitle;

  /// No description provided for @login.
  ///
  /// In ru, this message translates to:
  /// **'Войти'**
  String get login;

  /// No description provided for @forgotPassword.
  ///
  /// In ru, this message translates to:
  /// **'Забыли пароль?'**
  String get forgotPassword;

  /// No description provided for @recoverTitle.
  ///
  /// In ru, this message translates to:
  /// **'Восстановление доступа'**
  String get recoverTitle;

  /// No description provided for @recoveryCodeLabel.
  ///
  /// In ru, this message translates to:
  /// **'Код восстановления'**
  String get recoveryCodeLabel;

  /// No description provided for @newPasswordLabel.
  ///
  /// In ru, this message translates to:
  /// **'Новый пароль'**
  String get newPasswordLabel;

  /// No description provided for @recover.
  ///
  /// In ru, this message translates to:
  /// **'Восстановить'**
  String get recover;

  /// No description provided for @newRecoveryCode.
  ///
  /// In ru, this message translates to:
  /// **'Новый код восстановления — сохраните его'**
  String get newRecoveryCode;

  /// No description provided for @serverAddress.
  ///
  /// In ru, this message translates to:
  /// **'Адрес сервера'**
  String get serverAddress;

  /// No description provided for @serverAddressHelp.
  ///
  /// In ru, this message translates to:
  /// **'Если ваш вуз использует собственный сервер «Думыча»'**
  String get serverAddressHelp;

  /// No description provided for @qrDesktopLogin.
  ///
  /// In ru, this message translates to:
  /// **'Войти по QR с телефона'**
  String get qrDesktopLogin;

  /// No description provided for @qrDesktopHint.
  ///
  /// In ru, this message translates to:
  /// **'Откройте «Думыч» на телефоне → Настройки → «Войти на компьютере» и наведите камеру на код.'**
  String get qrDesktopHint;

  /// No description provided for @approveDesktopLogin.
  ///
  /// In ru, this message translates to:
  /// **'Войти на компьютере'**
  String get approveDesktopLogin;

  /// No description provided for @desktopLoginApproved.
  ///
  /// In ru, this message translates to:
  /// **'Вход на компьютере подтверждён'**
  String get desktopLoginApproved;

  /// No description provided for @navChat.
  ///
  /// In ru, this message translates to:
  /// **'Чат'**
  String get navChat;

  /// No description provided for @navSchedule.
  ///
  /// In ru, this message translates to:
  /// **'Расписание'**
  String get navSchedule;

  /// No description provided for @navDocuments.
  ///
  /// In ru, this message translates to:
  /// **'Документы'**
  String get navDocuments;

  /// No description provided for @navLectures.
  ///
  /// In ru, this message translates to:
  /// **'Конспекты'**
  String get navLectures;

  /// No description provided for @navSettings.
  ///
  /// In ru, this message translates to:
  /// **'Настройки'**
  String get navSettings;

  /// No description provided for @newChat.
  ///
  /// In ru, this message translates to:
  /// **'Новый чат'**
  String get newChat;

  /// No description provided for @chats.
  ///
  /// In ru, this message translates to:
  /// **'Чаты'**
  String get chats;

  /// No description provided for @noChats.
  ///
  /// In ru, this message translates to:
  /// **'Пока нет чатов'**
  String get noChats;

  /// No description provided for @inputHint.
  ///
  /// In ru, this message translates to:
  /// **'Спросите Думыча…'**
  String get inputHint;

  /// No description provided for @send.
  ///
  /// In ru, this message translates to:
  /// **'Отправить'**
  String get send;

  /// No description provided for @stop.
  ///
  /// In ru, this message translates to:
  /// **'Остановить'**
  String get stop;

  /// No description provided for @incognito.
  ///
  /// In ru, this message translates to:
  /// **'Инкогнито'**
  String get incognito;

  /// No description provided for @incognitoHint.
  ///
  /// In ru, this message translates to:
  /// **'Этот чат не сохраняется на сервере'**
  String get incognitoHint;

  /// No description provided for @holdToTalk.
  ///
  /// In ru, this message translates to:
  /// **'Удерживайте, чтобы говорить'**
  String get holdToTalk;

  /// No description provided for @tapToTalk.
  ///
  /// In ru, this message translates to:
  /// **'Нажмите, чтобы говорить'**
  String get tapToTalk;

  /// No description provided for @listening.
  ///
  /// In ru, this message translates to:
  /// **'Слушаю…'**
  String get listening;

  /// No description provided for @thinking.
  ///
  /// In ru, this message translates to:
  /// **'Думаю…'**
  String get thinking;

  /// No description provided for @toolSchedule.
  ///
  /// In ru, this message translates to:
  /// **'Смотрю расписание…'**
  String get toolSchedule;

  /// No description provided for @toolDocuments.
  ///
  /// In ru, this message translates to:
  /// **'Ищу в документах…'**
  String get toolDocuments;

  /// No description provided for @toolUniversity.
  ///
  /// In ru, this message translates to:
  /// **'Ищу в справке вуза…'**
  String get toolUniversity;

  /// No description provided for @toolNavigate.
  ///
  /// In ru, this message translates to:
  /// **'Строю маршрут…'**
  String get toolNavigate;

  /// No description provided for @sources.
  ///
  /// In ru, this message translates to:
  /// **'Источники'**
  String get sources;

  /// No description provided for @pageShort.
  ///
  /// In ru, this message translates to:
  /// **'стр. {page}'**
  String pageShort(int page);

  /// No description provided for @rename.
  ///
  /// In ru, this message translates to:
  /// **'Переименовать'**
  String get rename;

  /// No description provided for @renameChat.
  ///
  /// In ru, this message translates to:
  /// **'Переименовать чат'**
  String get renameChat;

  /// No description provided for @deleteChatConfirm.
  ///
  /// In ru, this message translates to:
  /// **'Удалить чат? Это действие нельзя отменить.'**
  String get deleteChatConfirm;

  /// No description provided for @helpful.
  ///
  /// In ru, this message translates to:
  /// **'Полезно'**
  String get helpful;

  /// No description provided for @notHelpful.
  ///
  /// In ru, this message translates to:
  /// **'Не помогло'**
  String get notHelpful;

  /// No description provided for @feedbackThanks.
  ///
  /// In ru, this message translates to:
  /// **'Спасибо за оценку!'**
  String get feedbackThanks;

  /// No description provided for @attachDialog.
  ///
  /// In ru, this message translates to:
  /// **'Приложить вопрос и ответ к оценке'**
  String get attachDialog;

  /// No description provided for @speak.
  ///
  /// In ru, this message translates to:
  /// **'Озвучить'**
  String get speak;

  /// No description provided for @documentScope.
  ///
  /// In ru, this message translates to:
  /// **'Вопросы по документам: {count}'**
  String documentScope(int count);

  /// No description provided for @emptyChatHint.
  ///
  /// In ru, this message translates to:
  /// **'Спросите что-нибудь: «Какая у меня следующая пара?», «Объясни производную», «Что сказано в методичке про отчёт?»'**
  String get emptyChatHint;

  /// No description provided for @micPermission.
  ///
  /// In ru, this message translates to:
  /// **'Нужен доступ к микрофону'**
  String get micPermission;

  /// No description provided for @voiceError.
  ///
  /// In ru, this message translates to:
  /// **'Не удалось распознать речь'**
  String get voiceError;

  /// No description provided for @shortcutsHint.
  ///
  /// In ru, this message translates to:
  /// **'Ctrl+Пробел — удерживайте для голоса · Ctrl+N — новый чат'**
  String get shortcutsHint;

  /// No description provided for @chooseGroup.
  ///
  /// In ru, this message translates to:
  /// **'Выбрать группу'**
  String get chooseGroup;

  /// No description provided for @groupSearch.
  ///
  /// In ru, this message translates to:
  /// **'Найти группу'**
  String get groupSearch;

  /// No description provided for @noGroup.
  ///
  /// In ru, this message translates to:
  /// **'Группа не выбрана'**
  String get noGroup;

  /// No description provided for @noClasses.
  ///
  /// In ru, this message translates to:
  /// **'Занятий нет'**
  String get noClasses;

  /// No description provided for @nowLabel.
  ///
  /// In ru, this message translates to:
  /// **'Сейчас'**
  String get nowLabel;

  /// No description provided for @nextLabel.
  ///
  /// In ru, this message translates to:
  /// **'Следующая'**
  String get nextLabel;

  /// No description provided for @today.
  ///
  /// In ru, this message translates to:
  /// **'Сегодня'**
  String get today;

  /// No description provided for @thisWeek.
  ///
  /// In ru, this message translates to:
  /// **'Эта неделя'**
  String get thisWeek;

  /// No description provided for @nextWeek.
  ///
  /// In ru, this message translates to:
  /// **'Следующая неделя'**
  String get nextWeek;

  /// No description provided for @roomShort.
  ///
  /// In ru, this message translates to:
  /// **'ауд. {room}'**
  String roomShort(String room);

  /// No description provided for @buildingShort.
  ///
  /// In ru, this message translates to:
  /// **'корп. {building}'**
  String buildingShort(String building);

  /// No description provided for @subgroupShort.
  ///
  /// In ru, this message translates to:
  /// **'подгруппа {n}'**
  String subgroupShort(String n);

  /// No description provided for @updatedAt.
  ///
  /// In ru, this message translates to:
  /// **'Обновлено {time}'**
  String updatedAt(String time);

  /// No description provided for @teacherSchedule.
  ///
  /// In ru, this message translates to:
  /// **'Расписание преподавателя'**
  String get teacherSchedule;

  /// No description provided for @upload.
  ///
  /// In ru, this message translates to:
  /// **'Загрузить'**
  String get upload;

  /// No description provided for @uploadHint.
  ///
  /// In ru, this message translates to:
  /// **'PDF, DOCX, XLSX, PPTX, TXT — до 20 МБ'**
  String get uploadHint;

  /// No description provided for @noDocuments.
  ///
  /// In ru, this message translates to:
  /// **'Документов пока нет'**
  String get noDocuments;

  /// No description provided for @statusQueued.
  ///
  /// In ru, this message translates to:
  /// **'В очереди'**
  String get statusQueued;

  /// No description provided for @statusProcessing.
  ///
  /// In ru, this message translates to:
  /// **'Обрабатывается'**
  String get statusProcessing;

  /// No description provided for @statusReady.
  ///
  /// In ru, this message translates to:
  /// **'Готов'**
  String get statusReady;

  /// No description provided for @statusFailed.
  ///
  /// In ru, this message translates to:
  /// **'Ошибка'**
  String get statusFailed;

  /// No description provided for @askDocument.
  ///
  /// In ru, this message translates to:
  /// **'Спросить по документу'**
  String get askDocument;

  /// No description provided for @deleteDocumentConfirm.
  ///
  /// In ru, this message translates to:
  /// **'Удалить документ вместе с поисковым индексом?'**
  String get deleteDocumentConfirm;

  /// No description provided for @pagesCount.
  ///
  /// In ru, this message translates to:
  /// **'{count} стр.'**
  String pagesCount(int count);

  /// No description provided for @uploadLecture.
  ///
  /// In ru, this message translates to:
  /// **'Загрузить запись'**
  String get uploadLecture;

  /// No description provided for @lectureTitle.
  ///
  /// In ru, this message translates to:
  /// **'Название лекции'**
  String get lectureTitle;

  /// No description provided for @teacherConsent.
  ///
  /// In ru, this message translates to:
  /// **'Преподаватель разрешил запись лекции'**
  String get teacherConsent;

  /// No description provided for @templateDetailed.
  ///
  /// In ru, this message translates to:
  /// **'Подробный конспект'**
  String get templateDetailed;

  /// No description provided for @templateShort.
  ///
  /// In ru, this message translates to:
  /// **'Краткий конспект'**
  String get templateShort;

  /// No description provided for @templateGlossary.
  ///
  /// In ru, this message translates to:
  /// **'Глоссарий'**
  String get templateGlossary;

  /// No description provided for @templateQuestions.
  ///
  /// In ru, this message translates to:
  /// **'Вопросы для самопроверки'**
  String get templateQuestions;

  /// No description provided for @lectureProcessing.
  ///
  /// In ru, this message translates to:
  /// **'Обработка: {percent}%'**
  String lectureProcessing(int percent);

  /// No description provided for @exportDocx.
  ///
  /// In ru, this message translates to:
  /// **'Скачать DOCX'**
  String get exportDocx;

  /// No description provided for @exportMd.
  ///
  /// In ru, this message translates to:
  /// **'Скачать Markdown'**
  String get exportMd;

  /// No description provided for @transcript.
  ///
  /// In ru, this message translates to:
  /// **'Расшифровка'**
  String get transcript;

  /// No description provided for @notes.
  ///
  /// In ru, this message translates to:
  /// **'Конспект'**
  String get notes;

  /// No description provided for @noLectures.
  ///
  /// In ru, this message translates to:
  /// **'Конспектов пока нет'**
  String get noLectures;

  /// No description provided for @chatWithLecture.
  ///
  /// In ru, this message translates to:
  /// **'Спросить по лекции'**
  String get chatWithLecture;

  /// No description provided for @savedTo.
  ///
  /// In ru, this message translates to:
  /// **'Сохранено: {path}'**
  String savedTo(String path);

  /// No description provided for @appearance.
  ///
  /// In ru, this message translates to:
  /// **'Оформление'**
  String get appearance;

  /// No description provided for @voiceSection.
  ///
  /// In ru, this message translates to:
  /// **'Голос'**
  String get voiceSection;

  /// No description provided for @autoSpeak.
  ///
  /// In ru, this message translates to:
  /// **'Читать ответы вслух'**
  String get autoSpeak;

  /// No description provided for @voiceSpeed.
  ///
  /// In ru, this message translates to:
  /// **'Скорость речи'**
  String get voiceSpeed;

  /// No description provided for @pushToTalkMode.
  ///
  /// In ru, this message translates to:
  /// **'Удерживать кнопку микрофона'**
  String get pushToTalkMode;

  /// No description provided for @privacy.
  ///
  /// In ru, this message translates to:
  /// **'Приватность'**
  String get privacy;

  /// No description provided for @historyRetention.
  ///
  /// In ru, this message translates to:
  /// **'Хранить историю чатов'**
  String get historyRetention;

  /// No description provided for @daysCount.
  ///
  /// In ru, this message translates to:
  /// **'{count, plural, one{{count} день} few{{count} дня} many{{count} дней} other{{count} дня}}'**
  String daysCount(int count);

  /// No description provided for @changePassword.
  ///
  /// In ru, this message translates to:
  /// **'Сменить пароль'**
  String get changePassword;

  /// No description provided for @currentPassword.
  ///
  /// In ru, this message translates to:
  /// **'Текущий пароль'**
  String get currentPassword;

  /// No description provided for @passwordChanged.
  ///
  /// In ru, this message translates to:
  /// **'Пароль изменён'**
  String get passwordChanged;

  /// No description provided for @deleteMyData.
  ///
  /// In ru, this message translates to:
  /// **'Удалить мои чаты, документы и конспекты'**
  String get deleteMyData;

  /// No description provided for @deleteMyDataConfirm.
  ///
  /// In ru, this message translates to:
  /// **'Все чаты, документы и конспекты будут удалены. Аккаунт останется.'**
  String get deleteMyDataConfirm;

  /// No description provided for @deleteAccount.
  ///
  /// In ru, this message translates to:
  /// **'Удалить аккаунт'**
  String get deleteAccount;

  /// No description provided for @deleteAccountConfirm.
  ///
  /// In ru, this message translates to:
  /// **'Аккаунт и все данные будут удалены без возможности восстановления. Введите пароль.'**
  String get deleteAccountConfirm;

  /// No description provided for @logout.
  ///
  /// In ru, this message translates to:
  /// **'Выйти'**
  String get logout;

  /// No description provided for @about.
  ///
  /// In ru, this message translates to:
  /// **'О приложении'**
  String get about;

  /// No description provided for @privacyNote.
  ///
  /// In ru, this message translates to:
  /// **'Мы не собираем телефон, почту и имя. Голос и кадры камеры не сохраняются, история шифруется.'**
  String get privacyNote;

  /// No description provided for @account.
  ///
  /// In ru, this message translates to:
  /// **'Аккаунт'**
  String get account;

  /// No description provided for @signedInAs.
  ///
  /// In ru, this message translates to:
  /// **'Вы вошли как {login}'**
  String signedInAs(String login);

  /// No description provided for @university.
  ///
  /// In ru, this message translates to:
  /// **'Вуз'**
  String get university;

  /// No description provided for @version.
  ///
  /// In ru, this message translates to:
  /// **'Версия {version}'**
  String version(String version);

  /// No description provided for @ttsUnavailable.
  ///
  /// In ru, this message translates to:
  /// **'Озвучка недоступна: не найден звуковой проигрыватель. Установите GStreamer (gstreamer1.0-plugins-good) или PipeWire/PulseAudio.'**
  String get ttsUnavailable;
}

class _DoomichLocalizationsDelegate
    extends LocalizationsDelegate<DoomichLocalizations> {
  const _DoomichLocalizationsDelegate();

  @override
  Future<DoomichLocalizations> load(Locale locale) {
    return SynchronousFuture<DoomichLocalizations>(
      lookupDoomichLocalizations(locale),
    );
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'ru'].contains(locale.languageCode);

  @override
  bool shouldReload(_DoomichLocalizationsDelegate old) => false;
}

DoomichLocalizations lookupDoomichLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return DoomichLocalizationsEn();
    case 'ru':
      return DoomichLocalizationsRu();
  }

  throw FlutterError(
    'DoomichLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
