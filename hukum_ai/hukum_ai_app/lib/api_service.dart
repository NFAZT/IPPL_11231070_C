import 'dart:convert';
import 'dart:async';
import 'package:http/http.dart' as http;

class SourceDoc {
  final String id;
  final String judul;
  final String isi;
  final double score;

  SourceDoc({
    required this.id,
    required this.judul,
    required this.isi,
    required this.score,
  });

  factory SourceDoc.fromJson(Map<String, dynamic> json) {
    final rawScore = json['score'];
    final scoreValue = (rawScore is num) ? rawScore.toDouble() : 0.0;

    return SourceDoc(
      id: json['id']?.toString() ?? '',
      judul: json['judul'] ?? '',
      isi: json['isi'] ?? '',
      score: scoreValue,
    );
  }
}

class ChatResponse {
  final String answer;
  final List<SourceDoc> sources;
  final int? sessionId;

  ChatResponse({
    required this.answer,
    required this.sources,
    this.sessionId,
  });

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    final sourcesJson = json['sources'] as List<dynamic>? ?? [];

    final rawSessionId = json['session_id'] ?? json['id'];
    int? sessionId;
    if (rawSessionId is int) {
      sessionId = rawSessionId;
    } else if (rawSessionId is String) {
      sessionId = int.tryParse(rawSessionId);
    }

    return ChatResponse(
      answer: json['answer'] ?? '',
      sources: sourcesJson
          .whereType<Map<String, dynamic>>()
          .map((e) => SourceDoc.fromJson(e))
          .toList(),
      sessionId: sessionId,
    );
  }
}

class ChatResult {
  final String answerText;
  final int? sessionId;
  final List<SourceDoc> sources;

  ChatResult({
    required this.answerText,
    required this.sessionId,
    required this.sources,
  });
}

class ChatSessionSummary {
  final int sessionId;
  final String title;
  final String? lastPreview;
  final String? createdAt;

  ChatSessionSummary({
    required this.sessionId,
    required this.title,
    this.lastPreview,
    this.createdAt,
  });

  factory ChatSessionSummary.fromJson(Map<String, dynamic> json) {
    final rawId = json['session_id'] ?? json['id'];
    int sessionId = 0;
    if (rawId is int) {
      sessionId = rawId;
    } else if (rawId is String) {
      sessionId = int.tryParse(rawId) ?? 0;
    }

    final title =
        (json['title'] as String?) ??
        (json['last_question'] as String?) ??
        (sessionId > 0 ? 'Konsultasi #$sessionId' : 'Konsultasi');

    final preview =
        (json['last_message_preview'] as String?) ??
        (json['last_answer_preview'] as String?) ??
        (json['last_message'] as String?) ??
        (json['last_question'] as String?) ??
        '';

    final createdAt = json['created_at']?.toString();

    return ChatSessionSummary(
      sessionId: sessionId,
      title: title,
      lastPreview: preview.isEmpty ? null : preview,
      createdAt: createdAt,
    );
  }
}

class ChatTurn {
  final String role;
  final String text;
  final String? createdAt;

  ChatTurn({
    required this.role,
    required this.text,
    this.createdAt,
  });

  bool get isUser => role.toLowerCase() == 'user';

  factory ChatTurn.fromJson(Map<String, dynamic> json) {
    return ChatTurn(
      role: json['role'] ?? 'assistant',
      text: json['text'] ?? json['content'] ?? '',
      createdAt: json['created_at']?.toString(),
    );
  }
}

class ChatSessionDetail {
  final int sessionId;
  final String username;
  final List<ChatTurn> messages;

  ChatSessionDetail({
    required this.sessionId,
    required this.username,
    required this.messages,
  });

  factory ChatSessionDetail.fromJson(Map<String, dynamic> json) {
    final rawId = json['session_id'] ?? json['id'];
    int sessionId = 0;
    if (rawId is int) {
      sessionId = rawId;
    } else if (rawId is String) {
      sessionId = int.tryParse(rawId) ?? 0;
    }

    final msgsJson = json['messages'] as List<dynamic>? ?? [];

    return ChatSessionDetail(
      sessionId: sessionId,
      username: json['username'] ?? '',
      messages: msgsJson
          .whereType<Map<String, dynamic>>()
          .map((e) => ChatTurn.fromJson(e))
          .toList(),
    );
  }
}

class AuthUser {
  final int id;
  final String username;
  final String email;
  final String? fullName;
  final bool isActive;

  AuthUser({
    required this.id,
    required this.username,
    required this.email,
    this.fullName,
    required this.isActive,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    return AuthUser(
      id: (json['id'] is int) ? (json['id'] as int) : int.tryParse('${json['id']}') ?? 0,
      username: json['username'] ?? '',
      email: json['email'] ?? '',
      fullName: json['full_name'] as String?,
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}

class ApiService {
  static const String defaultBaseUrl = 'https://api.hukumai.id';

  final String baseUrl;
  final http.Client _client;
  final Duration timeout;

  ApiService({
    String? baseUrl,
    http.Client? client,
    Duration? timeout,
  })  : baseUrl = (baseUrl?.trim().isNotEmpty ?? false) ? baseUrl!.trim() : defaultBaseUrl,
        _client = client ?? http.Client(),
        timeout = timeout ?? const Duration(seconds: 20);

  dynamic _decodeJsonBody(String body) {
    if (body.trim().isEmpty) return null;
    try {
      return jsonDecode(body);
    } catch (_) {
      return body;
    }
  }

  String _extractErrorMessage(int statusCode, dynamic decoded) {
    if (decoded is Map<String, dynamic>) {
      final detail = decoded['detail'];
      if (detail is String && detail.trim().isNotEmpty) {
        return detail.trim();
      }
      final message = decoded['message'];
      if (message is String && message.trim().isNotEmpty) {
        return message.trim();
      }
    }
    if (decoded is String && decoded.trim().isNotEmpty) {
      return decoded.trim();
    }
    return 'Request gagal. Status: $statusCode';
  }

  Future<ChatResult> askTrafficLaw(
    String question, {
    String? username,
    int? sessionId,
  }) async {
    final url = Uri.parse('$baseUrl/chat');

    final body = <String, dynamic>{
      'question': question,
    };

    if (username != null && username.trim().isNotEmpty) {
      body['username'] = username.trim();
    }

    if (sessionId != null) {
      body['session_id'] = sessionId;
    }

    http.Response response;
    try {
      response = await _client
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is! Map<String, dynamic>) {
        throw Exception('Format respons tidak sesuai (harus Map).');
      }

      final chatResp = ChatResponse.fromJson(decoded);

      String fullAnswer = chatResp.answer.trim();
      if (fullAnswer.isEmpty) {
        fullAnswer = 'Jawaban kosong dari server.';
      }

      return ChatResult(
        answerText: fullAnswer,
        sessionId: chatResp.sessionId,
        sources: chatResp.sources,
      );
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<List<ChatSessionSummary>> getChatHistory(String username) async {
    final url = Uri.parse('$baseUrl/chat-history/$username');

    http.Response response;
    try {
      response = await _client
          .get(
            url,
            headers: {'Content-Type': 'application/json'},
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is List) {
        return decoded
            .whereType<Map<String, dynamic>>()
            .map((e) => ChatSessionSummary.fromJson(e))
            .toList();
      }
      throw Exception('Format respons tidak sesuai (harus List).');
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<ChatSessionDetail> getChatSessionDetail(int sessionId) async {
    final url = Uri.parse('$baseUrl/chat-sessions/$sessionId');

    http.Response response;
    try {
      response = await _client
          .get(
            url,
            headers: {'Content-Type': 'application/json'},
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is! Map<String, dynamic>) {
        throw Exception('Format respons tidak sesuai (harus Map).');
      }
      return ChatSessionDetail.fromJson(decoded);
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<String> forgotPassword(String email) async {
    final url = Uri.parse('$baseUrl/auth/forgot-password');

    http.Response response;
    try {
      response = await _client
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'email': email}),
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is Map<String, dynamic>) {
        final msg = decoded['message'];
        if (msg is String && msg.trim().isNotEmpty) return msg.trim();
      }
      return 'Permintaan reset password diproses.';
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<String> resetPassword(String token, String newPassword) async {
    final url = Uri.parse('$baseUrl/auth/reset-password');

    http.Response response;
    try {
      response = await _client
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'token': token,
              'new_password': newPassword,
            }),
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is Map<String, dynamic>) {
        final msg = decoded['message'];
        if (msg is String && msg.trim().isNotEmpty) return msg.trim();
      }
      return 'Password berhasil direset.';
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<AuthUser> register(
    String username,
    String email,
    String password, {
    String? fullName,
  }) async {
    final url = Uri.parse('$baseUrl/auth/register');

    final body = <String, dynamic>{
      'username': username,
      'email': email,
      'password': password,
    };

    if (fullName != null && fullName.trim().isNotEmpty) {
      body['full_name'] = fullName.trim();
    }

    http.Response response;
    try {
      response = await _client
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is Map<String, dynamic>) {
        return AuthUser.fromJson(decoded);
      }
      throw Exception('Format respons register tidak sesuai.');
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }

  Future<AuthUser> login(String identifier, String password) async {
    final url = Uri.parse('$baseUrl/auth/login');

    http.Response response;
    try {
      response = await _client
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'identifier': identifier,
              'password': password,
            }),
          )
          .timeout(timeout);
    } on TimeoutException {
      throw Exception('Request timeout. Coba lagi.');
    } catch (e) {
      throw Exception('Gagal terhubung ke server: $e');
    }

    final decoded = _decodeJsonBody(response.body);

    if (response.statusCode == 200) {
      if (decoded is Map<String, dynamic> && decoded['user'] is Map<String, dynamic>) {
        return AuthUser.fromJson(decoded['user'] as Map<String, dynamic>);
      }
      throw Exception('Format respons login tidak sesuai.');
    } else {
      final msg = _extractErrorMessage(response.statusCode, decoded);
      throw Exception(msg);
    }
  }
}