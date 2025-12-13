import 'dart:convert';
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

    final rawSessionId = json['session_id'];
    int? sessionId;
    if (rawSessionId is int) {
      sessionId = rawSessionId;
    } else if (rawSessionId is String) {
      sessionId = int.tryParse(rawSessionId);
    }

    return ChatResponse(
      answer: json['answer'] ?? '',
      sources: sourcesJson
          .map((e) => SourceDoc.fromJson(e as Map<String, dynamic>))
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
      lastPreview: preview,
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
          .map((e) => ChatTurn.fromJson(e as Map<String, dynamic>))
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
      id: json['id'] as int,
      username: json['username'] ?? '',
      email: json['email'] ?? '',
      fullName: json['full_name'] as String?,
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}

class ApiService {
  static const String baseUrl = 'https://ippl11231070c-production.up.railway.app';

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

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final chatResp = ChatResponse.fromJson(data);

      String fullAnswer = chatResp.answer;

      if (chatResp.sources.isNotEmpty) {
        final judulList = chatResp.sources
            .map((s) => s.judul.trim())
            .where((j) => j.isNotEmpty)
            .toList();

        if (judulList.isNotEmpty) {
          final sumberText = "\n\nSumber: ${judulList.join(' ; ')}";
          fullAnswer += sumberText;
        }
      }

      if (fullAnswer.trim().isEmpty) {
        fullAnswer = 'Jawaban kosong dari server.';
      }

      return ChatResult(
        answerText: fullAnswer,
        sessionId: chatResp.sessionId,
        sources: chatResp.sources,
      );
    } else {
      throw Exception(
        'Gagal menghubungi server: ${response.statusCode}\n${response.body}',
      );
    }
  }

  Future<List<ChatSessionSummary>> getChatHistory(String username) async {
    final url = Uri.parse('$baseUrl/chat-history/$username');

    final response = await http.get(
      url,
      headers: {'Content-Type': 'application/json'},
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);

      if (data is List) {
        return data
            .map(
              (e) => ChatSessionSummary.fromJson(
                e as Map<String, dynamic>,
              ),
            )
            .toList();
      } else {
        throw Exception(
          'Format respons tidak sesuai (harus List). Dapat: ${data.runtimeType}',
        );
      }
    } else {
      throw Exception(
        'Gagal mengambil riwayat chat: ${response.statusCode}\n${response.body}',
      );
    }
  }

  Future<ChatSessionDetail> getChatSessionDetail(int sessionId) async {
    final url = Uri.parse('$baseUrl/chat-sessions/$sessionId');

    final response = await http.get(
      url,
      headers: {'Content-Type': 'application/json'},
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return ChatSessionDetail.fromJson(data);
    } else {
      throw Exception(
        'Gagal mengambil detail sesi: ${response.statusCode}\n${response.body}',
      );
    }
  }

  Future<String> forgotPassword(String email) async {
    final url = Uri.parse('$baseUrl/auth/forgot-password');

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email}),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is Map<String, dynamic>) {
        return data['message'] as String? ??
            'Permintaan reset password diproses.';
      }
      return 'Permintaan reset password diproses.';
    } else {
      throw Exception(
        'Gagal mengirim permintaan reset password: '
        '${response.statusCode}\n${response.body}',
      );
    }
  }

  Future<String> resetPassword(String token, String newPassword) async {
    final url = Uri.parse('$baseUrl/auth/reset-password');

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'token': token,
        'new_password': newPassword,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is Map<String, dynamic>) {
        return data['message'] as String? ?? 'Password berhasil direset.';
      }
      return 'Password berhasil direset.';
    } else {
      throw Exception(
        'Gagal reset password: ${response.statusCode}\n${response.body}',
      );
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

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data is Map<String, dynamic>) {
        return AuthUser.fromJson(data);
      } else {
        throw Exception('Format respons register tidak sesuai.');
      }
    } else {
      String message = 'Pendaftaran gagal.';
      try {
        final data = jsonDecode(response.body);
        if (data is Map<String, dynamic> && data['detail'] is String) {
          message = data['detail'] as String;
        }
      } catch (_) {}
      throw Exception(message);
    }
  }

  Future<AuthUser> login(String identifier, String password) async {
    final url = Uri.parse('$baseUrl/auth/login');

    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'identifier': identifier,
        'password': password,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);

      if (data is Map<String, dynamic> &&
          data['user'] is Map<String, dynamic>) {
        return AuthUser.fromJson(data['user'] as Map<String, dynamic>);
      } else {
        throw Exception('Format respons login tidak sesuai.');
      }
    } else {
      String message = 'Login gagal.';
      try {
        final data = jsonDecode(response.body);
        if (data is Map<String, dynamic> && data['detail'] is String) {
          message = data['detail'] as String;
        }
      } catch (_) {}
      throw Exception(message);
    }
  }
}