import 'package:doomich_core/doomich_core.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers.dart';
import '../settings.dart';
import '../widgets/common.dart';

DateTime mondayOf(DateTime day) {
  final d = DateTime(day.year, day.month, day.day);
  return d.subtract(Duration(days: d.weekday - 1));
}

/// Неделя расписания: группа пользователя или выбранный на устройстве преподаватель.
final scheduleWeekProvider = FutureProvider.autoDispose.family<ScheduleResult, DateTime>((ref, monday) async {
  final repo = await ref.watch(scheduleRepositoryProvider.future);
  final me = ref.watch(sessionProvider).value;
  final teacher = ref.watch(settingsProvider.select((s) => s.teacherName));
  if (me == null) return const ScheduleResult([]);
  if (teacher != null && me.isTeacher) {
    return repo.events(monday, monday.add(const Duration(days: 6)), teacher: teacher);
  }
  if (me.group == null) return const ScheduleResult([]);
  return repo.events(monday, monday.add(const Duration(days: 6)));
});

class ScheduleScreen extends ConsumerStatefulWidget {
  const ScheduleScreen({super.key});

  @override
  ConsumerState<ScheduleScreen> createState() => _ScheduleScreenState();
}

class _ScheduleScreenState extends ConsumerState<ScheduleScreen> {
  late DateTime _monday = mondayOf(_now());

  /// Пары показываются по часам вуза, где бы ни было устройство.
  DateTime _now() => ref.read(sessionProvider).value?.university.now() ?? DateTime.now();

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final me = ref.watch(sessionProvider).value;
    final teacher = ref.watch(settingsProvider.select((s) => s.teacherName));
    final week = ref.watch(scheduleWeekProvider(_monday));
    final now = me?.university.now() ?? DateTime.now();
    final current = mondayOf(now);
    final heading = teacher != null && (me?.isTeacher ?? false)
        ? teacher
        : (me?.group != null ? l10n.groupLabel(me!.group!.code) : l10n.noGroup);
    return Scaffold(
      appBar: AppBar(
        title: Text(heading),
        actions: [
          if (me?.isTeacher ?? false)
            IconButton(
              tooltip: l10n.teacherSchedule,
              icon: const Icon(Icons.person_search_outlined),
              onPressed: () => _pickTeacher(context),
            ),
          IconButton(tooltip: l10n.chooseGroup, icon: const Icon(Icons.groups_outlined), onPressed: () => pickGroup(context, ref)),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: Row(
              children: [
                IconButton(
                  icon: const Icon(Icons.chevron_left),
                  onPressed: () => setState(() => _monday = _monday.subtract(const Duration(days: 7))),
                ),
                Expanded(
                  child: Text(
                    _monday == current
                        ? l10n.thisWeek
                        : (_monday == current.add(const Duration(days: 7))
                              ? l10n.nextWeek
                              : '${ddmm(_monday)} – ${ddmm(_monday.add(const Duration(days: 6)))}'),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.chevron_right),
                  onPressed: () => setState(() => _monday = _monday.add(const Duration(days: 7))),
                ),
                TextButton(onPressed: () => setState(() => _monday = current), child: Text(l10n.today)),
              ],
            ),
          ),
          Expanded(
            child: me?.group == null && teacher == null
                ? EmptyState(
                    icon: Icons.groups_outlined,
                    text: l10n.noGroup,
                    action: FilledButton(onPressed: () => pickGroup(context, ref), child: Text(l10n.chooseGroup)),
                  )
                : AsyncView(
                    value: week,
                    onRetry: () => ref.invalidate(scheduleWeekProvider(_monday)),
                    builder: (result) => RefreshIndicator(
                      onRefresh: () => ref.refresh(scheduleWeekProvider(_monday).future),
                      child: _WeekList(result: result, now: now),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Future<void> _pickTeacher(BuildContext context) async {
    final l10n = context.l10n;
    final name = await promptText(context, title: l10n.teacherSchedule, initial: ref.read(settingsProvider).teacherName ?? '');
    if (name == null) return;
    await ref.read(settingsProvider.notifier).setTeacher(name.trim().isEmpty ? null : name.trim());
  }
}

class _WeekList extends StatelessWidget {
  const _WeekList({required this.result, required this.now});

  final ScheduleResult result;

  /// «Сейчас» по часам вуза.
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final byDay = <DateTime, List<ScheduleEvent>>{};
    for (final e in result.events) {
      byDay.putIfAbsent(DateTime(e.startsAt.year, e.startsAt.month, e.startsAt.day), () => []).add(e);
    }
    final next = result.events.where((e) => e.startsAt.isAfter(now)).firstOrNull;
    final children = <Widget>[
      if (result.offline)
        MaterialBanner(
          leading: const Icon(Icons.cloud_off),
          content: Text(l10n.offlineBadge('${ddmm(result.savedAt!)} ${hhmm(result.savedAt!)}')),
          actions: const [SizedBox.shrink()],
        ),
    ];
    if (byDay.isEmpty) {
      children.add(Padding(padding: const EdgeInsets.all(32), child: Center(child: Text(l10n.noClasses))));
    }
    final locale = Localizations.localeOf(context).languageCode;
    const ru = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'];
    const en = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    for (final entry in byDay.entries) {
      final isToday = entry.key == DateTime(now.year, now.month, now.day);
      children.add(
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Text(
            '${(locale == 'en' ? en : ru)[entry.key.weekday - 1]}, ${ddmm(entry.key)}${isToday ? ' · ${l10n.today}' : ''}',
            style: Theme.of(context).textTheme.titleSmall?.copyWith(color: isToday ? Theme.of(context).colorScheme.primary : null),
          ),
        ),
      );
      for (final event in entry.value) {
        children.add(_EventCard(event: event, isNow: event.isNow(now), isNext: identical(event, next)));
      }
    }
    return ListView(children: children);
  }
}

class _EventCard extends StatelessWidget {
  const _EventCard({required this.event, required this.isNow, required this.isNext});

  final ScheduleEvent event;
  final bool isNow;
  final bool isNext;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    final scheme = Theme.of(context).colorScheme;
    final details = [
      if (event.kind != null) event.kind!,
      if (event.room != null) l10n.roomShort(event.room!),
      if (event.building != null) l10n.buildingShort(event.building!),
      if (event.subgroup != null) l10n.subgroupShort(event.subgroup!),
      if (event.teacher != null) event.teacher!,
    ].join(' · ');
    return Card(
      color: isNow ? scheme.primaryContainer : null,
      child: ListTile(
        leading: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [Text(hhmm(event.startsAt), style: const TextStyle(fontWeight: FontWeight.w600)), Text(hhmm(event.endsAt))],
        ),
        title: Text(event.subject),
        subtitle: details.isEmpty ? null : Text(details),
        trailing: isNow
            ? Chip(label: Text(l10n.nowLabel))
            : (isNext ? Chip(label: Text(l10n.nextLabel), backgroundColor: scheme.secondaryContainer) : null),
      ),
    );
  }
}

/// Выбор группы из списка групп вуза.
Future<void> pickGroup(BuildContext context, WidgetRef ref) async {
  final group = await showDialog<StudyGroup>(context: context, builder: (_) => const _GroupDialog());
  if (group == null || !context.mounted) return;
  await guarded(context, () => ref.read(sessionProvider.notifier).updateMe(groupId: group.id));
  ref.invalidate(scheduleWeekProvider);
}

class _GroupDialog extends ConsumerStatefulWidget {
  const _GroupDialog();

  @override
  ConsumerState<_GroupDialog> createState() => _GroupDialogState();
}

class _GroupDialogState extends ConsumerState<_GroupDialog> {
  List<StudyGroup> _groups = const [];
  bool _loading = false;

  Future<void> _search(String q) async {
    setState(() => _loading = true);
    try {
      final groups = await ref.read(authRepositoryProvider).groups(q);
      if (mounted) setState(() => _groups = groups);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void initState() {
    super.initState();
    _search('');
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return AlertDialog(
      title: Text(l10n.chooseGroup),
      content: SizedBox(
        width: 360,
        height: 420,
        child: Column(
          children: [
            TextField(
              autofocus: true,
              decoration: InputDecoration(prefixIcon: const Icon(Icons.search), hintText: l10n.groupSearch),
              onChanged: _search,
            ),
            const SizedBox(height: 8),
            if (_loading) const LinearProgressIndicator(),
            Expanded(
              child: ListView(
                children: [
                  for (final g in _groups)
                    ListTile(
                      title: Text(g.code),
                      subtitle: g.name == null && g.faculty == null ? null : Text([g.name, g.faculty].whereType<String>().join(' · ')),
                      onTap: () => Navigator.pop(context, g),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
      actions: [TextButton(onPressed: () => Navigator.pop(context), child: Text(l10n.cancel))],
    );
  }
}
