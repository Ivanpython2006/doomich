// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'doomich_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Russian (`ru`).
class DoomichLocalizationsRu extends DoomichLocalizations {
  DoomichLocalizationsRu([String locale = 'ru']) : super(locale);

  @override
  String get appTitle => 'Думыч';

  @override
  String get ok => 'ОК';

  @override
  String get cancel => 'Отмена';

  @override
  String get save => 'Сохранить';

  @override
  String get delete => 'Удалить';

  @override
  String get retry => 'Повторить';

  @override
  String get close => 'Закрыть';

  @override
  String get next => 'Далее';

  @override
  String get back => 'Назад';

  @override
  String get copy => 'Скопировать';

  @override
  String get copied => 'Скопировано';

  @override
  String get loading => 'Загрузка…';

  @override
  String get errorGeneric => 'Что-то пошло не так';

  @override
  String offlineBadge(String time) {
    return 'Нет сети — сохранённая копия от $time';
  }

  @override
  String get welcomeTitle => 'Привет! Я Думыч';

  @override
  String get welcomeSubtitle =>
      'ИИ-помощник для учёбы: отвечаю на вопросы текстом и голосом, знаю расписание и читаю ваши документы.';

  @override
  String get welcomePrivacy =>
      'Без телефона, почты и имени — только псевдоним.';

  @override
  String get language => 'Язык';

  @override
  String get theme => 'Тема';

  @override
  String get themeSystem => 'Как в системе';

  @override
  String get themeLight => 'Светлая';

  @override
  String get themeDark => 'Тёмная';

  @override
  String get start => 'Начать';

  @override
  String get haveAccount => 'У меня уже есть аккаунт';

  @override
  String get inviteTitle => 'Код приглашения';

  @override
  String get inviteHelp =>
      'Код выдаёт вуз или куратор группы. Можно отсканировать QR-код.';

  @override
  String get scanQr => 'Сканировать QR';

  @override
  String get inviteInvalid => 'Код недействителен или уже использован';

  @override
  String inviteJoining(String university) {
    return 'Вы присоединяетесь к «$university»';
  }

  @override
  String get roleStudent => 'студент';

  @override
  String get roleTeacher => 'преподаватель';

  @override
  String groupLabel(String group) {
    return 'Группа $group';
  }

  @override
  String get accountTitle => 'Создайте аккаунт';

  @override
  String get pseudonymLabel => 'Псевдоним';

  @override
  String get pseudonymHelp =>
      'Не используйте настоящее имя — так мы не храним персональные данные.';

  @override
  String get pseudonymLooksLikeName =>
      'Похоже на настоящее имя. Лучше выберите псевдоним.';

  @override
  String get pseudonymTaken => 'Этот псевдоним уже занят';

  @override
  String get suggestions => 'Варианты';

  @override
  String get passwordLabel => 'Пароль';

  @override
  String get passwordHelp => 'Не короче 10 символов';

  @override
  String get passwordWeak => 'Слабый пароль';

  @override
  String get passwordMedium => 'Средний пароль';

  @override
  String get passwordStrong => 'Надёжный пароль';

  @override
  String get agreeTerms =>
      'Я принимаю пользовательское соглашение и правила обработки данных';

  @override
  String get createAccount => 'Создать аккаунт';

  @override
  String get recoveryTitle => 'Код восстановления';

  @override
  String get recoveryText =>
      'Это единственный способ вернуть доступ: у нас нет вашей почты и телефона. Сохраните код в надёжном месте.';

  @override
  String get recoverySaved => 'Я сохранил код';

  @override
  String get saveToFile => 'Сохранить в файл';

  @override
  String get loginTitle => 'Вход';

  @override
  String get login => 'Войти';

  @override
  String get forgotPassword => 'Забыли пароль?';

  @override
  String get recoverTitle => 'Восстановление доступа';

  @override
  String get recoveryCodeLabel => 'Код восстановления';

  @override
  String get newPasswordLabel => 'Новый пароль';

  @override
  String get recover => 'Восстановить';

  @override
  String get newRecoveryCode => 'Новый код восстановления — сохраните его';

  @override
  String get serverAddress => 'Адрес сервера';

  @override
  String get serverAddressHelp =>
      'Если ваш вуз использует собственный сервер «Думыча»';

  @override
  String get qrDesktopLogin => 'Войти по QR с телефона';

  @override
  String get qrDesktopHint =>
      'Откройте «Думыч» на телефоне → Настройки → «Войти на компьютере» и наведите камеру на код.';

  @override
  String get approveDesktopLogin => 'Войти на компьютере';

  @override
  String get desktopLoginApproved => 'Вход на компьютере подтверждён';

  @override
  String get navChat => 'Чат';

  @override
  String get navSchedule => 'Расписание';

  @override
  String get navDocuments => 'Документы';

  @override
  String get navLectures => 'Конспекты';

  @override
  String get navSettings => 'Настройки';

  @override
  String get newChat => 'Новый чат';

  @override
  String get chats => 'Чаты';

  @override
  String get noChats => 'Пока нет чатов';

  @override
  String get inputHint => 'Спросите Думыча…';

  @override
  String get send => 'Отправить';

  @override
  String get stop => 'Остановить';

  @override
  String get incognito => 'Инкогнито';

  @override
  String get incognitoHint => 'Этот чат не сохраняется на сервере';

  @override
  String get holdToTalk => 'Удерживайте, чтобы говорить';

  @override
  String get tapToTalk => 'Нажмите, чтобы говорить';

  @override
  String get listening => 'Слушаю…';

  @override
  String get thinking => 'Думаю…';

  @override
  String get toolSchedule => 'Смотрю расписание…';

  @override
  String get toolDocuments => 'Ищу в документах…';

  @override
  String get toolUniversity => 'Ищу в справке вуза…';

  @override
  String get toolNavigate => 'Строю маршрут…';

  @override
  String get sources => 'Источники';

  @override
  String pageShort(int page) {
    return 'стр. $page';
  }

  @override
  String get rename => 'Переименовать';

  @override
  String get renameChat => 'Переименовать чат';

  @override
  String get deleteChatConfirm => 'Удалить чат? Это действие нельзя отменить.';

  @override
  String get helpful => 'Полезно';

  @override
  String get notHelpful => 'Не помогло';

  @override
  String get feedbackThanks => 'Спасибо за оценку!';

  @override
  String get attachDialog => 'Приложить вопрос и ответ к оценке';

  @override
  String get speak => 'Озвучить';

  @override
  String documentScope(int count) {
    return 'Вопросы по документам: $count';
  }

  @override
  String get emptyChatHint =>
      'Спросите что-нибудь: «Какая у меня следующая пара?», «Объясни производную», «Что сказано в методичке про отчёт?»';

  @override
  String get micPermission => 'Нужен доступ к микрофону';

  @override
  String get voiceError => 'Не удалось распознать речь';

  @override
  String get shortcutsHint =>
      'Ctrl+Пробел — удерживайте для голоса · Ctrl+N — новый чат';

  @override
  String get chooseGroup => 'Выбрать группу';

  @override
  String get groupSearch => 'Найти группу';

  @override
  String get noGroup => 'Группа не выбрана';

  @override
  String get noClasses => 'Занятий нет';

  @override
  String get nowLabel => 'Сейчас';

  @override
  String get nextLabel => 'Следующая';

  @override
  String get today => 'Сегодня';

  @override
  String get thisWeek => 'Эта неделя';

  @override
  String get nextWeek => 'Следующая неделя';

  @override
  String roomShort(String room) {
    return 'ауд. $room';
  }

  @override
  String buildingShort(String building) {
    return 'корп. $building';
  }

  @override
  String subgroupShort(String n) {
    return 'подгруппа $n';
  }

  @override
  String updatedAt(String time) {
    return 'Обновлено $time';
  }

  @override
  String get teacherSchedule => 'Расписание преподавателя';

  @override
  String get upload => 'Загрузить';

  @override
  String get uploadHint => 'PDF, DOCX, XLSX, PPTX, TXT — до 20 МБ';

  @override
  String get noDocuments => 'Документов пока нет';

  @override
  String get statusQueued => 'В очереди';

  @override
  String get statusProcessing => 'Обрабатывается';

  @override
  String get statusReady => 'Готов';

  @override
  String get statusFailed => 'Ошибка';

  @override
  String get askDocument => 'Спросить по документу';

  @override
  String get deleteDocumentConfirm =>
      'Удалить документ вместе с поисковым индексом?';

  @override
  String pagesCount(int count) {
    return '$count стр.';
  }

  @override
  String get uploadLecture => 'Загрузить запись';

  @override
  String get lectureTitle => 'Название лекции';

  @override
  String get teacherConsent => 'Преподаватель разрешил запись лекции';

  @override
  String get templateDetailed => 'Подробный конспект';

  @override
  String get templateShort => 'Краткий конспект';

  @override
  String get templateGlossary => 'Глоссарий';

  @override
  String get templateQuestions => 'Вопросы для самопроверки';

  @override
  String lectureProcessing(int percent) {
    return 'Обработка: $percent%';
  }

  @override
  String get exportDocx => 'Скачать DOCX';

  @override
  String get exportMd => 'Скачать Markdown';

  @override
  String get transcript => 'Расшифровка';

  @override
  String get notes => 'Конспект';

  @override
  String get noLectures => 'Конспектов пока нет';

  @override
  String get chatWithLecture => 'Спросить по лекции';

  @override
  String savedTo(String path) {
    return 'Сохранено: $path';
  }

  @override
  String get appearance => 'Оформление';

  @override
  String get voiceSection => 'Голос';

  @override
  String get autoSpeak => 'Читать ответы вслух';

  @override
  String get voiceSpeed => 'Скорость речи';

  @override
  String get pushToTalkMode => 'Удерживать кнопку микрофона';

  @override
  String get privacy => 'Приватность';

  @override
  String get historyRetention => 'Хранить историю чатов';

  @override
  String daysCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count дня',
      many: '$count дней',
      few: '$count дня',
      one: '$count день',
    );
    return '$_temp0';
  }

  @override
  String get changePassword => 'Сменить пароль';

  @override
  String get currentPassword => 'Текущий пароль';

  @override
  String get passwordChanged => 'Пароль изменён';

  @override
  String get deleteMyData => 'Удалить мои чаты, документы и конспекты';

  @override
  String get deleteMyDataConfirm =>
      'Все чаты, документы и конспекты будут удалены. Аккаунт останется.';

  @override
  String get deleteAccount => 'Удалить аккаунт';

  @override
  String get deleteAccountConfirm =>
      'Аккаунт и все данные будут удалены без возможности восстановления. Введите пароль.';

  @override
  String get logout => 'Выйти';

  @override
  String get about => 'О приложении';

  @override
  String get privacyNote =>
      'Мы не собираем телефон, почту и имя. Голос и кадры камеры не сохраняются, история шифруется.';

  @override
  String get account => 'Аккаунт';

  @override
  String signedInAs(String login) {
    return 'Вы вошли как $login';
  }

  @override
  String get university => 'Вуз';

  @override
  String version(String version) {
    return 'Версия $version';
  }

  @override
  String get ttsUnavailable =>
      'Озвучка недоступна: не найден звуковой проигрыватель. Установите GStreamer (gstreamer1.0-plugins-good) или PipeWire/PulseAudio.';
}
