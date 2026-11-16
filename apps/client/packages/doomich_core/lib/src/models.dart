// Модели данных API «Думыча». Разбор JSON вручную — без генерации кода.

DateTime _dt(Object? v) => DateTime.parse(v as String).toLocal();
DateTime? _dtOrNull(Object? v) => v == null ? null : _dt(v);

final _withOffset = RegExp(r'^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?)[+-]\d{2}(?::?\d{2})?$');

/// Время «по часам» из ISO 8601 со смещением — без перевода в часовой пояс устройства.
///
/// Сервер отдаёт время пар в часовом поясе вуза (`2026-11-16T09:00:00+03:00`), и показывать его нужно
/// именно так, где бы ни было устройство. `DateTime.parse` перевёл бы время в UTC и потерял смещение.
/// Время без смещения или в UTC (старый сервер) переводится в пояс устройства, как раньше.
DateTime wallClock(String iso) {
  final match = _withOffset.firstMatch(iso.trim());
  return match == null ? DateTime.parse(iso).toLocal() : DateTime.parse(match.group(1)!);
}

/// «Сейчас» по часам пояса со смещением [utcOffset] (без смещения — по часам устройства).
DateTime wallNow(Duration? utcOffset, {DateTime? now}) {
  final at = now ?? DateTime.now();
  if (utcOffset == null) return at;
  final t = at.toUtc().add(utcOffset);
  return DateTime(t.year, t.month, t.day, t.hour, t.minute, t.second, t.millisecond);
}

class University {
  const University({required this.id, required this.slug, required this.name, required this.timezone, this.utcOffset});

  factory University.fromJson(Map<String, dynamic> j) => University(
    id: j['id'] as String,
    slug: j['slug'] as String,
    name: j['name'] as String,
    timezone: j['timezone'] as String,
    utcOffset: j['utc_offset_minutes'] == null ? null : Duration(minutes: j['utc_offset_minutes'] as int),
  );

  final String id;
  final String slug;
  final String name;
  final String timezone;

  /// Текущее смещение часового пояса вуза от UTC (по данным сервера).
  final Duration? utcOffset;

  /// «Сейчас» по часам вуза — для сравнения со временем пар.
  DateTime now() => wallNow(utcOffset);
}

class StudyGroup {
  const StudyGroup({required this.id, required this.code, this.name, this.faculty});

  factory StudyGroup.fromJson(Map<String, dynamic> j) => StudyGroup(
    id: j['id'] as String,
    code: j['code'] as String,
    name: j['name'] as String?,
    faculty: j['faculty'] as String?,
  );

  final String id;
  final String code;
  final String? name;
  final String? faculty;
}

class Me {
  const Me({
    required this.id,
    required this.login,
    required this.role,
    required this.locale,
    required this.historyDays,
    required this.university,
    this.group,
    this.features = const {},
  });

  factory Me.fromJson(Map<String, dynamic> j) => Me(
    id: j['id'] as String,
    login: j['login'] as String,
    role: j['role'] as String,
    locale: j['locale'] as String,
    historyDays: j['history_days'] as int,
    university: University.fromJson(j['university'] as Map<String, dynamic>),
    group: j['group'] == null ? null : StudyGroup.fromJson(j['group'] as Map<String, dynamic>),
    features: (j['features'] as Map<String, dynamic>? ?? {}).map((k, v) => MapEntry(k, v == true)),
  );

  final String id;
  final String login;
  final String role;
  final String locale;
  final int historyDays;
  final University university;
  final StudyGroup? group;
  final Map<String, bool> features;

  bool get isTeacher => role == 'teacher';
  bool feature(String name) => features[name] ?? false;
}

class AuthResult {
  const AuthResult({required this.accessToken, required this.refreshToken, required this.user, this.recoveryCode});

  factory AuthResult.fromJson(Map<String, dynamic> j) => AuthResult(
    accessToken: j['access_token'] as String,
    refreshToken: j['refresh_token'] as String,
    user: Me.fromJson(j['user'] as Map<String, dynamic>),
    recoveryCode: j['recovery_code'] as String?,
  );

  final String accessToken;
  final String refreshToken;
  final Me user;

  /// Показывается один раз после регистрации или восстановления доступа.
  final String? recoveryCode;
}

class InviteInfo {
  const InviteInfo({required this.valid, this.university, this.role, this.group});

  factory InviteInfo.fromJson(Map<String, dynamic> j) => InviteInfo(
    valid: j['valid'] as bool,
    university: j['university'] as String?,
    role: j['role'] as String?,
    group: j['group'] as String?,
  );

  final bool valid;
  final String? university;
  final String? role;
  final String? group;
}

class LoginCheck {
  const LoginCheck({required this.available, required this.valid, required this.looksLikeName, this.problem});

  factory LoginCheck.fromJson(Map<String, dynamic> j) => LoginCheck(
    available: j['available'] as bool,
    valid: j['valid'] as bool,
    looksLikeName: j['looks_like_name'] as bool,
    problem: j['problem'] as String?,
  );

  final bool available;
  final bool valid;
  final bool looksLikeName;
  final String? problem;
}

class ChatSummary {
  const ChatSummary({
    required this.id,
    required this.title,
    required this.documentIds,
    required this.createdAt,
    required this.updatedAt,
    this.expiresAt,
  });

  factory ChatSummary.fromJson(Map<String, dynamic> j) => ChatSummary(
    id: j['id'] as String,
    title: j['title'] as String,
    documentIds: (j['document_ids'] as List? ?? const []).cast<String>(),
    createdAt: _dt(j['created_at']),
    updatedAt: _dt(j['updated_at']),
    expiresAt: _dtOrNull(j['expires_at']),
  );

  final String id;
  final String title;
  final List<String> documentIds;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? expiresAt;
}

class Citation {
  const Citation({
    required this.n,
    required this.documentId,
    required this.chunkId,
    required this.title,
    this.page,
    this.section,
    this.snippet = '',
  });

  factory Citation.fromJson(Map<String, dynamic> j) => Citation(
    n: j['n'] as int,
    documentId: j['document_id'] as String,
    chunkId: j['chunk_id'] as String,
    title: j['title'] as String? ?? '',
    page: j['page'] as int?,
    section: j['section'] as String?,
    snippet: j['snippet'] as String? ?? '',
  );

  final int n;
  final String documentId;
  final String chunkId;
  final String title;
  final int? page;
  final String? section;
  final String snippet;
}

class ChatMessage {
  ChatMessage({
    required this.id,
    required this.author,
    required this.content,
    this.citations = const [],
    this.mode = 'text',
    DateTime? createdAt,
  }) : createdAt = createdAt ?? DateTime.now();

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
    id: j['id'] as String,
    author: j['author'] as String,
    content: j['content'] as String,
    citations: (j['citations'] as List? ?? const []).map((c) => Citation.fromJson(c as Map<String, dynamic>)).toList(),
    mode: j['mode'] as String? ?? 'text',
    createdAt: _dt(j['created_at']),
  );

  final String id;
  final String author; // user | assistant
  String content;
  List<Citation> citations;
  final String mode;
  final DateTime createdAt;

  bool get isUser => author == 'user';

  Map<String, String> toHistory() => {'role': author, 'content': content};
}

class ScheduleEvent {
  const ScheduleEvent({
    required this.id,
    required this.uid,
    required this.startsAt,
    required this.endsAt,
    required this.subject,
    this.kind,
    this.room,
    this.building,
    this.teacher,
    this.subgroup,
    this.note,
  });

  factory ScheduleEvent.fromJson(Map<String, dynamic> j) => ScheduleEvent(
    id: j['id'] as String,
    uid: j['uid'] as String,
    startsAt: wallClock(j['starts_at'] as String),
    endsAt: wallClock(j['ends_at'] as String),
    subject: j['subject'] as String,
    kind: j['kind'] as String?,
    room: j['room'] as String?,
    building: j['building'] as String?,
    teacher: j['teacher'] as String?,
    subgroup: j['subgroup'] as String?,
    note: j['note'] as String?,
  );

  final String id;
  final String uid;

  /// Начало и конец пары по часам вуза (см. [wallClock]); сравнивать с [University.now].
  final DateTime startsAt;
  final DateTime endsAt;
  final String subject;
  final String? kind;
  final String? room;
  final String? building;
  final String? teacher;
  final String? subgroup;
  final String? note;

  bool isNow(DateTime at) => !at.isBefore(startsAt) && at.isBefore(endsAt);
}

class ScheduleChange {
  const ScheduleChange({required this.id, required this.eventUid, required this.change, required this.payload, required this.createdAt});

  factory ScheduleChange.fromJson(Map<String, dynamic> j) => ScheduleChange(
    id: j['id'] as int,
    eventUid: j['event_uid'] as String,
    change: j['change'] as String,
    payload: (j['payload'] as Map).cast<String, dynamic>(),
    createdAt: _dt(j['created_at']),
  );

  final int id;
  final String eventUid;
  final String change; // added | removed | changed
  final Map<String, dynamic> payload;
  final DateTime createdAt;
}

class DocumentInfo {
  const DocumentInfo({
    required this.id,
    required this.title,
    required this.ownerType,
    required this.mime,
    required this.sizeBytes,
    required this.status,
    required this.createdAt,
    this.pages,
    this.error,
  });

  factory DocumentInfo.fromJson(Map<String, dynamic> j) => DocumentInfo(
    id: j['id'] as String,
    title: j['title'] as String,
    ownerType: j['owner_type'] as String,
    mime: j['mime'] as String,
    sizeBytes: j['size_bytes'] as int,
    status: j['status'] as String,
    createdAt: _dt(j['created_at']),
    pages: j['pages'] as int?,
    error: j['error'] as String?,
  );

  final String id;
  final String title;
  final String ownerType;
  final String mime;
  final int sizeBytes;
  final String status; // queued | processing | ready | failed
  final DateTime createdAt;
  final int? pages;
  final String? error;

  bool get isReady => status == 'ready';
  bool get isBusy => status == 'queued' || status == 'processing';
}

class SourceChunk {
  const SourceChunk({required this.id, required this.documentId, required this.body, this.page, this.section});

  factory SourceChunk.fromJson(Map<String, dynamic> j) => SourceChunk(
    id: j['id'] as String,
    documentId: j['document_id'] as String,
    body: j['body'] as String,
    page: j['page'] as int?,
    section: j['section'] as String?,
  );

  final String id;
  final String documentId;
  final String body;
  final int? page;
  final String? section;
}

class Lecture {
  const Lecture({
    required this.id,
    required this.title,
    required this.status,
    required this.template,
    required this.progress,
    required this.createdAt,
    this.durationS,
    this.notes,
    this.transcript,
    this.documentId,
    this.error,
  });

  factory Lecture.fromJson(Map<String, dynamic> j) => Lecture(
    id: j['id'] as String,
    title: j['title'] as String,
    status: j['status'] as String,
    template: j['template'] as String,
    progress: (j['progress'] as num).toDouble(),
    createdAt: _dt(j['created_at']),
    durationS: (j['duration_s'] as num?)?.toDouble(),
    notes: j['notes'] as String?,
    transcript: j['transcript'] as String?,
    documentId: j['document_id'] as String?,
    error: j['error'] as String?,
  );

  final String id;
  final String title;
  final String status;
  final String template;
  final double progress;
  final DateTime createdAt;
  final double? durationS;
  final String? notes;
  final String? transcript;
  final String? documentId;
  final String? error;

  bool get isReady => status == 'ready';
  bool get isFailed => status == 'failed';
}

class RouteResult {
  const RouteResult({required this.lengthM, required this.steps});

  factory RouteResult.fromJson(Map<String, dynamic> j) =>
      RouteResult(lengthM: (j['length_m'] as num).toDouble(), steps: (j['steps'] as List).cast<String>());

  final double lengthM;
  final List<String> steps;
}
