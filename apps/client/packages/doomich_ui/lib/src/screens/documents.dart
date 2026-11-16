import 'package:doomich_core/doomich_core.dart';
import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat_controller.dart';
import '../providers.dart';
import '../widgets/common.dart';

const documentExtensions = ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md'];

/// Выбрать файл и вернуть (имя, байты).
Future<(String, List<int>)?> pickFile(List<String> extensions) async {
  final file = await FilePicker.pickFile(type: FileType.custom, allowedExtensions: extensions);
  if (file == null) return null;
  return (file.name, (await file.readAsBytes()).toList());
}

class DocumentsScreen extends ConsumerWidget {
  const DocumentsScreen({super.key, required this.onAsk});

  /// Открыть чат с вопросами по выбранным документам.
  final void Function(ChatKey key) onAsk;

  Future<void> _upload(BuildContext context, WidgetRef ref) async {
    final picked = await pickFile(documentExtensions);
    if (picked == null || !context.mounted) return;
    await guarded(context, () => ref.read(documentsProvider.notifier).upload(picked.$1, picked.$2));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final docs = ref.watch(documentsProvider);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.navDocuments)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _upload(context, ref),
        icon: const Icon(Icons.upload_file),
        label: Text(l10n.upload),
      ),
      body: AsyncView(
        value: docs,
        onRetry: () => ref.invalidate(documentsProvider),
        builder: (items) => items.isEmpty
            ? EmptyState(icon: Icons.folder_open_outlined, text: '${l10n.noDocuments}\n${l10n.uploadHint}')
            : RefreshIndicator(
                onRefresh: () => ref.refresh(documentsProvider.future),
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 96),
                  children: [
                    Padding(padding: const EdgeInsets.all(16), child: Text(l10n.uploadHint)),
                    for (final doc in items) _DocumentTile(doc: doc, onAsk: onAsk),
                  ],
                ),
              ),
      ),
    );
  }
}

class _DocumentTile extends ConsumerWidget {
  const _DocumentTile({required this.doc, required this.onAsk});

  final DocumentInfo doc;
  final void Function(ChatKey key) onAsk;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = context.l10n;
    final status = switch (doc.status) {
      'queued' => l10n.statusQueued,
      'processing' => l10n.statusProcessing,
      'ready' => l10n.statusReady,
      _ => l10n.statusFailed,
    };
    final icon = switch (doc.mime) {
      final m when m.contains('pdf') => Icons.picture_as_pdf_outlined,
      final m when m.contains('sheet') => Icons.table_chart_outlined,
      final m when m.contains('presentation') => Icons.slideshow_outlined,
      _ => Icons.description_outlined,
    };
    return Card(
      child: ListTile(
        leading: Icon(icon),
        title: Text(doc.title, maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text(
          [
            status,
            formatBytes(doc.sizeBytes),
            if (doc.pages != null) l10n.pagesCount(doc.pages!),
            if (doc.error != null) doc.error!,
          ].join(' · '),
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (doc.isBusy) const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)),
            if (doc.isReady)
              IconButton(
                tooltip: l10n.askDocument,
                icon: const Icon(Icons.question_answer_outlined),
                onPressed: () async {
                  final chat = await guarded(
                    context,
                    () => ref.read(chatListProvider.notifier).create(documentIds: [doc.id], title: doc.title),
                  );
                  if (chat != null) onAsk(ChatKey.server(chat.id, documentIds: [doc.id]));
                },
              ),
            IconButton(
              tooltip: l10n.delete,
              icon: const Icon(Icons.delete_outline),
              onPressed: () async {
                if (await confirm(context, l10n.deleteDocumentConfirm, danger: true) && context.mounted) {
                  await guarded(context, () => ref.read(documentsProvider.notifier).remove(doc.id));
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}
