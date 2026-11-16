import 'dart:async';
import 'dart:convert';

/// Событие Server-Sent Events.
class SseEvent {
  const SseEvent(this.event, this.data);

  final String event;
  final Map<String, dynamic> data;

  @override
  String toString() => 'SseEvent($event, $data)';
}

/// Разбор потока байтов SSE в события (event + JSON-данные).
class SseParser extends StreamTransformerBase<List<int>, SseEvent> {
  const SseParser();

  @override
  Stream<SseEvent> bind(Stream<List<int>> stream) async* {
    var event = 'message';
    final data = StringBuffer();
    await for (final line in stream.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (data.isNotEmpty) {
          final raw = data.toString();
          Map<String, dynamic> payload;
          try {
            final decoded = jsonDecode(raw);
            payload = decoded is Map<String, dynamic> ? decoded : {'value': decoded};
          } on FormatException {
            payload = {'raw': raw};
          }
          yield SseEvent(event, payload);
        }
        event = 'message';
        data.clear();
      } else if (line.startsWith('event:')) {
        event = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        if (data.isNotEmpty) data.write('\n');
        data.write(line.substring(5).trimLeft());
      }
    }
    if (data.isNotEmpty) {
      yield SseEvent(event, jsonDecode(data.toString()) as Map<String, dynamic>);
    }
  }
}
