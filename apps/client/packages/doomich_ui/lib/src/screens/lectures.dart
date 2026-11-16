import 'package:doomich_core/doomich_core.dart';
import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gpt_markdown/gpt_markdown.dart';

import '../chat_controller.dart';
import '../providers.dart';
import '../widgets/common.dart';
import 'documents.dart';

const audioExtensions = ['mp3', 'm4a', 'wav', 'ogg', 'opus', 'webm', 'mp4', 'aac', 'flac'];

/// Конспекты лекций (R1.1): запись или файл → расшифровка → конспект → экспорт и «чат с лекцией».
class LecturesScreen extends ConsumerWidget {
  const LecturesScreen({super.key, required this.onAsk});

  final void Function(ChatKey key) onAsk;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final lectures = ref.watch(lecturesProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.navLectures)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showDialog<void>(context: context, builder: (_) => const _UploadLectureDialog()),
        icon: const Icon(Icons.mic_external_on_outlined),
        label: Text(l10n.uploadLecture),
      ),
      body: AsyncView(
        value: lectures,
        onRetry: () => ref.invalidate(lecturesProvider),
        builder: (items) => items.isEmpty
            ? EmptyState(icon: Icons.note_alt_outlined, text: l10n.noLectures)
            : ListView(
                padding: const EdgeInsets.only(bottom: 96),
                children: [
                  for (final lecture in items)
                    Card(
                      child: ListTile(
                        leading: Icon(lecture.isReady ? Icons.article_outlined : (lecture.isFailed ? Icons.error_outline : Icons.hourglass_top)),
                        title: Text(lecture.title),
                        subtitle: Text(
                          lecture.isReady
                              ? '${ddmm(lecture.createdAt)} · ${((lecture.durationS ?? 0) / 60).round()} мин'
                              : (lecture.isFailed ? (lecture.error ?? l10n.statusFailed) : l10n.lectureProcessing((lecture.progress * 100).round())),
                        ),
                        onTap: lecture.isReady
                            ? () => Navigator.push(
                                context,
                                MaterialPageRoute(builder: (_) => LectureDetailScreen(lectureId: lecture.id, onAsk: onAsk)),
                              )
                            : null,
                        trailing: IconButton(
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () async {
                            if (await confirm(context, '${l10n.delete}?', danger: true) && context.mounted) {
                              await guarded(context, () => ref.read(lecturesProvider.notifier).remove(lecture.id));
                            }
                          },
                        ),
                      ),
                    ),
                ],
              ),
      ),
    );
  }
}

class _UploadLectureDialog extends ConsumerStatefulWidget {
  const _UploadLectureDialog();

  @override
  ConsumerState<_UploadLectureDialog> createState() => _UploadLectureDialogState();
}

class _UploadLectureDialogState extends ConsumerState<_UploadLectureDialog> {
  final _title = TextEditingController();
  String _template = 'detailed';
  bool _consent = false;
  (String, List<int>)? _file;
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final l10n = context.l10n;
    return AlertDialog(
      title: Text(l10n.uploadLecture),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _title, decoration: InputDecoration(labelText: l10n.lectureTitle)),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              icon: const Icon(Icons.audio_file_outlined),
              label: Text(_file?.$1 ?? audioExtensions.join(', ')),
              onPressed: () async {
                final picked = await pickFile(audioExtensions);
                if (picked != null) setState(() => _file = picked);
              },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _template,
              items: [
                DropdownMenuItem(value: 'detailed', child: Text(l10n.templateDetailed)),
                DropdownMenuItem(value: 'short', child: Text(l10n.templateShort)),
                DropdownMenuItem(value: 'glossary', child: Text(l10n.templateGlossary)),
                DropdownMenuItem(value: 'questions', child: Text(l10n.templateQuestions)),
              ],
              onChanged: (v) => setState(() => _template = v ?? 'detailed'),
            ),
            CheckboxListTile(
              value: _consent,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text(l10n.teacherConsent),
              onChanged: (v) => setState(() => _consent = v ?? false),
            ),
            if (_busy) const LinearProgressIndicator(),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(l10n.cancel)),
        FilledButton(
          onPressed: _file != null && _consent && _title.text.trim().isNotEmpty && !_busy
              ? () async {
                  setState(() => _busy = true);
                  final ok = await guarded(context, () async {
                    await ref.read(lecturesProvider.notifier).upload(
                      filename: _file!.$1,
                      bytes: _file!.$2,
                      title: _title.text.trim(),
                      template: _template,
                      consent: _consent,
                    );
                    return true;
                  });
                  if (!context.mounted) return;
                  if (ok == true) {
                    Navigator.pop(context);
                  } else {
                    setState(() => _busy = false);
                  }
                }
              : null,
          child: Text(l10n.upload),
        ),
      ],
    );
  }
}

final _lectureProvider = FutureProvider.autoDispose.family<Lecture, String>(
  (ref, id) => ref.watch(lecturesRepositoryProvider).get(id),
);

class LectureDetailScreen extends ConsumerWidget {
  const LectureDetailScreen({super.key, required this.lectureId, required this.onAsk});

  final String lectureId;
  final void Function(ChatKey key) onAsk;

  Future<void> _export(BuildContext context, WidgetRef ref, Lecture lecture, String format) async {
    final bytes = await guarded(context, () => ref.read(lecturesRepositoryProvider).export(lecture.id, format: format));
    if (bytes == null) return;
    final uri = await FilePicker.saveFile(fileName: '${lecture.title}.$format', bytes: bytes);
    if (uri != null && context.mounted) showMessage(context, context.l10n.savedTo(uri.toFilePath()));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final lecture = ref.watch(_lectureProvider(lectureId));
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(lecture.value?.title ?? l10n.notes),
          bottom: TabBar(tabs: [Tab(text: l10n.notes), Tab(text: l10n.transcript)]),
          actions: [
            if (lecture.value?.documentId != null)
              IconButton(
                tooltip: l10n.chatWithLecture,
                icon: const Icon(Icons.question_answer_outlined),
                onPressed: () async {
                  final value = lecture.value!;
                  final chat = await guarded(
                    context,
                    () => ref.read(chatListProvider.notifier).create(documentIds: [value.documentId!], title: value.title),
                  );
                  if (chat != null && context.mounted) {
                    Navigator.pop(context);
                    onAsk(ChatKey.server(chat.id, documentIds: [value.documentId!]));
                  }
                },
              ),
            PopupMenuButton<String>(
              onSelected: (format) => _export(context, ref, lecture.value!, format),
              itemBuilder: (_) => [
                PopupMenuItem(value: 'docx', child: Text(l10n.exportDocx)),
                PopupMenuItem(value: 'md', child: Text(l10n.exportMd)),
              ],
            ),
          ],
        ),
        body: AsyncView(
          value: lecture,
          builder: (value) => TabBarView(
            children: [
              SingleChildScrollView(padding: const EdgeInsets.all(16), child: GptMarkdown(value.notes ?? '')),
              SingleChildScrollView(padding: const EdgeInsets.all(16), child: SelectableText(value.transcript ?? '')),
            ],
          ),
        ),
      ),
    );
  }
}
