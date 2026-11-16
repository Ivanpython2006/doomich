import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';

import 'sse.dart';

/// Ошибка API с понятным пользователю текстом (сервер отвечает по-русски или по-английски).
class ApiException implements Exception {
  const ApiException(this.message, {this.status});

  final String message;
  final int? status;

  bool get isUnauthorized => status == 401;
  bool get isNetwork => status == null;

  @override
  String toString() => message;
}

/// Хранилище токенов. На устройствах — защищённое хранилище ОС (см. doomich_ui).
abstract class TokenStore {
  Future<String?> readAccess();
  Future<String?> readRefresh();
  Future<void> save(String access, String refresh);
  Future<void> clear();
}

class MemoryTokenStore implements TokenStore {
  String? _access;
  String? _refresh;

  @override
  Future<String?> readAccess() async => _access;
  @override
  Future<String?> readRefresh() async => _refresh;
  @override
  Future<void> save(String access, String refresh) async {
    _access = access;
    _refresh = refresh;
  }

  @override
  Future<void> clear() async => _access = _refresh = null;
}

/// HTTP-клиент: токен в заголовке, автоматическое обновление сессии, разбор ошибок, SSE.
class ApiClient {
  ApiClient({required Uri baseUrl, required this.tokens, Dio? dio, this.onSessionExpired})
    : dio = dio ?? Dio() {
    this.dio.options
      ..baseUrl = baseUrl.toString()
      ..connectTimeout = const Duration(seconds: 15)
      ..receiveTimeout = const Duration(minutes: 3)
      ..headers['Accept'] = 'application/json';
    this.dio.interceptors.add(
      QueuedInterceptorsWrapper(onRequest: _authorize, onError: _refreshOn401),
    );
  }

  final Dio dio;
  final TokenStore tokens;
  final void Function()? onSessionExpired;
  Completer<bool>? _refreshing;

  Uri get baseUrl => Uri.parse(dio.options.baseUrl);

  Future<void> _authorize(RequestOptions options, RequestInterceptorHandler handler) async {
    if (options.extra['auth'] != false) {
      final token = await tokens.readAccess();
      if (token != null) options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  /// Dio без перехватчиков: обновление токена и повтор запроса не должны снова попадать
  /// в очередь перехватчиков (иначе ошибка внутри обработчика ошибок блокирует очередь).
  late final Dio _bare = Dio(dio.options.copyWith())..httpClientAdapter = dio.httpClientAdapter;

  Future<void> _refreshOn401(DioException error, ErrorInterceptorHandler handler) async {
    final options = error.requestOptions;
    if (error.response?.statusCode != 401 || options.extra['auth'] == false || options.extra['retried'] == true) {
      return handler.next(error);
    }
    final used = options.headers['Authorization'];
    final current = await tokens.readAccess();
    // токен уже обновил параллельный запрос — просто повторяем с новым
    final refreshed = (current != null && used != 'Bearer $current') || await refreshSession();
    if (refreshed) {
      options.extra['retried'] = true;
      options.headers['Authorization'] = 'Bearer ${await tokens.readAccess()}';
      try {
        return handler.resolve(await _bare.fetch(options));
      } on DioException catch (e) {
        return handler.next(e);
      }
    }
    onSessionExpired?.call();
    handler.next(error);
  }

  /// Обновить пару токенов. Параллельные вызовы ждут один и тот же запрос.
  Future<bool> refreshSession() async {
    if (_refreshing != null) return _refreshing!.future;
    final completer = _refreshing = Completer<bool>();
    try {
      final refresh = await tokens.readRefresh();
      if (refresh == null) {
        completer.complete(false);
        return false;
      }
      final resp = await _bare.post<Map<String, dynamic>>('/v1/auth/refresh', data: {'refresh_token': refresh});
      final body = resp.data!;
      await tokens.save(body['access_token'] as String, body['refresh_token'] as String);
      completer.complete(true);
      return true;
    } catch (_) {
      await tokens.clear();
      completer.complete(false);
      return false;
    } finally {
      _refreshing = null;
    }
  }

  static ApiException mapError(Object error) {
    if (error is ApiException) return error;
    if (error is DioException) {
      final response = error.response;
      if (response == null) {
        return const ApiException('Нет связи с сервером. Проверьте интернет.');
      }
      final data = response.data;
      String? detail;
      if (data is Map && data['detail'] != null) {
        final d = data['detail'];
        detail = d is String ? d : (d is List && d.isNotEmpty ? (d.first as Map)['msg']?.toString() : d.toString());
      }
      return ApiException(detail ?? 'Ошибка сервера (${response.statusCode})', status: response.statusCode);
    }
    return ApiException(error.toString());
  }

  Future<T> _wrap<T>(Future<Response<dynamic>> Function() call) async {
    try {
      final resp = await call();
      return resp.data as T;
    } catch (e) {
      throw mapError(e);
    }
  }

  Future<T> get<T>(String path, {Map<String, dynamic>? query, bool auth = true}) =>
      _wrap(() => dio.get<dynamic>(path, queryParameters: query, options: Options(extra: {'auth': auth})));

  Future<T> post<T>(String path, {Object? body, bool auth = true}) =>
      _wrap(() => dio.post<dynamic>(path, data: body, options: Options(extra: {'auth': auth})));

  Future<T> patch<T>(String path, {Object? body}) => _wrap(() => dio.patch<dynamic>(path, data: body));

  Future<T> put<T>(String path, {Object? body}) => _wrap(() => dio.put<dynamic>(path, data: body));

  Future<T> delete<T>(String path, {Object? body}) => _wrap(() => dio.delete<dynamic>(path, data: body));

  Future<Uint8List> getBytes(String path, {Map<String, dynamic>? query}) async {
    try {
      final resp = await dio.get<List<int>>(
        path,
        queryParameters: query,
        options: Options(responseType: ResponseType.bytes),
      );
      return Uint8List.fromList(resp.data!);
    } catch (e) {
      throw mapError(e);
    }
  }

  Future<Map<String, dynamic>> upload(
    String path, {
    required String filename,
    required List<int> bytes,
    Map<String, dynamic> fields = const {},
    void Function(int sent, int total)? onProgress,
  }) => _wrap(
    () => dio.post<dynamic>(
      path,
      data: FormData.fromMap({...fields, 'file': MultipartFile.fromBytes(bytes, filename: filename)}),
      onSendProgress: onProgress,
    ),
  );

  /// POST с потоковым ответом (Server-Sent Events).
  Stream<SseEvent> postSse(String path, Object body, {CancelToken? cancel}) async* {
    Response<ResponseBody> resp;
    try {
      resp = await dio.post<ResponseBody>(
        path,
        data: body,
        cancelToken: cancel,
        options: Options(responseType: ResponseType.stream, headers: {'Accept': 'text/event-stream'}),
      );
    } catch (e) {
      throw mapError(e);
    }
    yield* resp.data!.stream.cast<List<int>>().transform(const SseParser());
  }
}
