// ignore: unused_import
import 'package:intl/intl.dart' as intl;

import 'doomich_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class DoomichLocalizationsEn extends DoomichLocalizations {
  DoomichLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Doomich';

  @override
  String get ok => 'OK';

  @override
  String get cancel => 'Cancel';

  @override
  String get save => 'Save';

  @override
  String get delete => 'Delete';

  @override
  String get retry => 'Retry';

  @override
  String get close => 'Close';

  @override
  String get next => 'Next';

  @override
  String get back => 'Back';

  @override
  String get copy => 'Copy';

  @override
  String get copied => 'Copied';

  @override
  String get loading => 'Loading…';

  @override
  String get errorGeneric => 'Something went wrong';

  @override
  String offlineBadge(String time) {
    return 'Offline — saved copy from $time';
  }

  @override
  String get welcomeTitle => 'Hi! I\'m Doomich';

  @override
  String get welcomeSubtitle =>
      'Your study assistant: I answer by text and voice, know your schedule and read your documents.';

  @override
  String get welcomePrivacy => 'No phone, e-mail or name — just a nickname.';

  @override
  String get language => 'Language';

  @override
  String get theme => 'Theme';

  @override
  String get themeSystem => 'System';

  @override
  String get themeLight => 'Light';

  @override
  String get themeDark => 'Dark';

  @override
  String get start => 'Get started';

  @override
  String get haveAccount => 'I already have an account';

  @override
  String get inviteTitle => 'Invite code';

  @override
  String get inviteHelp =>
      'Your university or group curator gives you the code. You can scan the QR code.';

  @override
  String get scanQr => 'Scan QR';

  @override
  String get inviteInvalid => 'The code is invalid or already used';

  @override
  String inviteJoining(String university) {
    return 'You are joining «$university»';
  }

  @override
  String get roleStudent => 'student';

  @override
  String get roleTeacher => 'teacher';

  @override
  String groupLabel(String group) {
    return 'Group $group';
  }

  @override
  String get accountTitle => 'Create an account';

  @override
  String get pseudonymLabel => 'Nickname';

  @override
  String get pseudonymHelp =>
      'Don\'t use your real name — this way we store no personal data.';

  @override
  String get pseudonymLooksLikeName =>
      'This looks like a real name. Better pick a nickname.';

  @override
  String get pseudonymTaken => 'This nickname is taken';

  @override
  String get suggestions => 'Suggestions';

  @override
  String get passwordLabel => 'Password';

  @override
  String get passwordHelp => 'At least 10 characters';

  @override
  String get passwordWeak => 'Weak password';

  @override
  String get passwordMedium => 'Fair password';

  @override
  String get passwordStrong => 'Strong password';

  @override
  String get agreeTerms =>
      'I accept the terms of use and the data processing rules';

  @override
  String get createAccount => 'Create account';

  @override
  String get recoveryTitle => 'Recovery code';

  @override
  String get recoveryText =>
      'This is the only way to restore access: we don\'t have your e-mail or phone. Keep the code somewhere safe.';

  @override
  String get recoverySaved => 'I saved the code';

  @override
  String get saveToFile => 'Save to file';

  @override
  String get loginTitle => 'Sign in';

  @override
  String get login => 'Sign in';

  @override
  String get forgotPassword => 'Forgot password?';

  @override
  String get recoverTitle => 'Restore access';

  @override
  String get recoveryCodeLabel => 'Recovery code';

  @override
  String get newPasswordLabel => 'New password';

  @override
  String get recover => 'Restore';

  @override
  String get newRecoveryCode => 'Your new recovery code — save it';

  @override
  String get serverAddress => 'Server address';

  @override
  String get serverAddressHelp =>
      'If your university runs its own Doomich server';

  @override
  String get qrDesktopLogin => 'Sign in with phone QR';

  @override
  String get qrDesktopHint =>
      'Open Doomich on your phone → Settings → «Sign in on computer» and point the camera at the code.';

  @override
  String get approveDesktopLogin => 'Sign in on computer';

  @override
  String get desktopLoginApproved => 'Computer sign-in approved';

  @override
  String get navChat => 'Chat';

  @override
  String get navSchedule => 'Schedule';

  @override
  String get navDocuments => 'Documents';

  @override
  String get navLectures => 'Notes';

  @override
  String get navSettings => 'Settings';

  @override
  String get newChat => 'New chat';

  @override
  String get chats => 'Chats';

  @override
  String get noChats => 'No chats yet';

  @override
  String get inputHint => 'Ask Doomich…';

  @override
  String get send => 'Send';

  @override
  String get stop => 'Stop';

  @override
  String get incognito => 'Incognito';

  @override
  String get incognitoHint => 'This chat is not stored on the server';

  @override
  String get holdToTalk => 'Hold to talk';

  @override
  String get tapToTalk => 'Tap to talk';

  @override
  String get listening => 'Listening…';

  @override
  String get thinking => 'Thinking…';

  @override
  String get toolSchedule => 'Checking the schedule…';

  @override
  String get toolDocuments => 'Searching documents…';

  @override
  String get toolUniversity => 'Searching university info…';

  @override
  String get toolNavigate => 'Planning a route…';

  @override
  String get sources => 'Sources';

  @override
  String pageShort(int page) {
    return 'p. $page';
  }

  @override
  String get rename => 'Rename';

  @override
  String get renameChat => 'Rename chat';

  @override
  String get deleteChatConfirm => 'Delete the chat? This can\'t be undone.';

  @override
  String get helpful => 'Helpful';

  @override
  String get notHelpful => 'Not helpful';

  @override
  String get feedbackThanks => 'Thanks for the feedback!';

  @override
  String get attachDialog => 'Attach the question and answer';

  @override
  String get speak => 'Read aloud';

  @override
  String documentScope(int count) {
    return 'Questions about documents: $count';
  }

  @override
  String get emptyChatHint =>
      'Ask anything: «What\'s my next class?», «Explain derivatives», «What does the guide say about the report?»';

  @override
  String get micPermission => 'Microphone access is required';

  @override
  String get voiceError => 'Couldn\'t recognize speech';

  @override
  String get shortcutsHint => 'Ctrl+Space — hold to talk · Ctrl+N — new chat';

  @override
  String get chooseGroup => 'Choose group';

  @override
  String get groupSearch => 'Find group';

  @override
  String get noGroup => 'No group selected';

  @override
  String get noClasses => 'No classes';

  @override
  String get nowLabel => 'Now';

  @override
  String get nextLabel => 'Next';

  @override
  String get today => 'Today';

  @override
  String get thisWeek => 'This week';

  @override
  String get nextWeek => 'Next week';

  @override
  String roomShort(String room) {
    return 'room $room';
  }

  @override
  String buildingShort(String building) {
    return 'bldg $building';
  }

  @override
  String subgroupShort(String n) {
    return 'subgroup $n';
  }

  @override
  String updatedAt(String time) {
    return 'Updated $time';
  }

  @override
  String get teacherSchedule => 'Teacher schedule';

  @override
  String get upload => 'Upload';

  @override
  String get uploadHint => 'PDF, DOCX, XLSX, PPTX, TXT — up to 20 MB';

  @override
  String get noDocuments => 'No documents yet';

  @override
  String get statusQueued => 'Queued';

  @override
  String get statusProcessing => 'Processing';

  @override
  String get statusReady => 'Ready';

  @override
  String get statusFailed => 'Failed';

  @override
  String get askDocument => 'Ask about document';

  @override
  String get deleteDocumentConfirm =>
      'Delete the document and its search index?';

  @override
  String pagesCount(int count) {
    return '$count pp.';
  }

  @override
  String get uploadLecture => 'Upload recording';

  @override
  String get lectureTitle => 'Lecture title';

  @override
  String get teacherConsent => 'The teacher allowed recording';

  @override
  String get templateDetailed => 'Detailed notes';

  @override
  String get templateShort => 'Short notes';

  @override
  String get templateGlossary => 'Glossary';

  @override
  String get templateQuestions => 'Self-check questions';

  @override
  String lectureProcessing(int percent) {
    return 'Processing: $percent%';
  }

  @override
  String get exportDocx => 'Download DOCX';

  @override
  String get exportMd => 'Download Markdown';

  @override
  String get transcript => 'Transcript';

  @override
  String get notes => 'Notes';

  @override
  String get noLectures => 'No notes yet';

  @override
  String get chatWithLecture => 'Ask about lecture';

  @override
  String savedTo(String path) {
    return 'Saved: $path';
  }

  @override
  String get appearance => 'Appearance';

  @override
  String get voiceSection => 'Voice';

  @override
  String get autoSpeak => 'Read answers aloud';

  @override
  String get voiceSpeed => 'Speech rate';

  @override
  String get pushToTalkMode => 'Hold the mic button';

  @override
  String get privacy => 'Privacy';

  @override
  String get historyRetention => 'Keep chat history';

  @override
  String daysCount(int count) {
    String _temp0 = intl.Intl.pluralLogic(
      count,
      locale: localeName,
      other: '$count days',
      one: '$count day',
    );
    return '$_temp0';
  }

  @override
  String get changePassword => 'Change password';

  @override
  String get currentPassword => 'Current password';

  @override
  String get passwordChanged => 'Password changed';

  @override
  String get deleteMyData => 'Delete my chats, documents and notes';

  @override
  String get deleteMyDataConfirm =>
      'All chats, documents and notes will be deleted. The account stays.';

  @override
  String get deleteAccount => 'Delete account';

  @override
  String get deleteAccountConfirm =>
      'The account and all data will be deleted permanently. Enter your password.';

  @override
  String get logout => 'Sign out';

  @override
  String get about => 'About';

  @override
  String get privacyNote =>
      'We don\'t collect phone, e-mail or name. Voice and camera frames are not stored, history is encrypted.';

  @override
  String get account => 'Account';

  @override
  String signedInAs(String login) {
    return 'Signed in as $login';
  }

  @override
  String get university => 'University';

  @override
  String version(String version) {
    return 'Version $version';
  }

  @override
  String get ttsUnavailable =>
      'Read-aloud is unavailable: no audio player found. Install GStreamer (gstreamer1.0-plugins-good) or PipeWire/PulseAudio.';
}
