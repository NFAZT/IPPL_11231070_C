import 'package:flutter/material.dart';
import 'api_service.dart';

class ChatMessage {
  final String id;
  final String text;
  final bool isUser;
  final DateTime timestamp;

  ChatMessage({
    required this.id,
    required this.text,
    required this.isUser,
    required this.timestamp,
  });
}

class HomePage extends StatefulWidget {
  final String? username;

  const HomePage({Key? key, this.username}) : super(key: key);

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final ApiService _apiService = ApiService();
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  final List<ChatMessage> _messages = [];
  bool _isSending = false;
  bool _isTyping = false;

  String? _username;
  int? _currentSessionId;
  bool _initialRouteHandled = false;

  String get _effectiveUsername => _username ?? 'anon';
  bool get _isLoggedIn => _username != null;

  @override
  void initState() {
    super.initState();
    _username = widget.username;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();

    if (_initialRouteHandled) return;
    _initialRouteHandled = true;

    final args = ModalRoute.of(context)?.settings.arguments;
    if (args is Map) {
      if (args['username'] is String && _username == null) {
        _username = args['username'] as String;
      }
      if (args['initialSessionId'] is int) {
        final sessionId = args['initialSessionId'] as int;
        _currentSessionId = sessionId;
        _loadSessionFromServer(sessionId);
      }
    }
  }

  DateTime _parseServerDateTime(String? raw) {
    if (raw == null || raw.isEmpty) return DateTime.now();
    try {
      return DateTime.parse(raw).toLocal();
    } catch (_) {
      return DateTime.now();
    }
  }

  Future<void> _loadSessionFromServer(int sessionId) async {
    setState(() {
      _isSending = true;
      _messages.clear();
    });

    try {
      final detail = await _apiService.getChatSessionDetail(sessionId);

      final loaded = detail.messages.map((turn) {
        return ChatMessage(
          id: '${turn.role}-${turn.createdAt ?? DateTime.now().toIso8601String()}',
          text: turn.text,
          isUser: turn.isUser,
          timestamp: _parseServerDateTime(turn.createdAt),
        );
      }).toList();

      setState(() {
        _currentSessionId = detail.sessionId;
        _messages
          ..clear()
          ..addAll(loaded);
      });

      _scrollToBottom();
    } catch (e) {
      setState(() {
        _messages.add(
          ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch.toString(),
            text: 'Gagal memuat riwayat sesi: $e',
            isUser: false,
            timestamp: DateTime.now(),
          ),
        );
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _isSending = false;
      });
    }
  }

  Future<void> _sendMessage() async {
    final question = _controller.text.trim();
    if (question.isEmpty || _isSending) return;

    final userMessage = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      text: question,
      isUser: true,
      timestamp: DateTime.now(),
    );

    setState(() {
      _isSending = true;
      _messages.add(userMessage);
      _controller.clear();
    });

    _scrollToBottom();

    try {
      final result = await _apiService.askTrafficLaw(
        question,
        username: _isLoggedIn ? _effectiveUsername : null,
        sessionId: _isLoggedIn ? _currentSessionId : null,
      );

      setState(() {
        if (result.sessionId != null && _isLoggedIn) {
          _currentSessionId = result.sessionId;
        }
        _isTyping = true;
      });

      await Future.delayed(const Duration(milliseconds: 500));

      final botMessage = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        text: result.answerText,
        isUser: false,
        timestamp: DateTime.now(),
      );

      setState(() {
        _messages.add(botMessage);
        _isTyping = false;
      });
      _scrollToBottom();
    } catch (e) {
      final errorMessage = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        text: 'Terjadi kesalahan saat menghubungi server: $e',
        isUser: false,
        timestamp: DateTime.now(),
      );
      setState(() {
        _messages.add(errorMessage);
      });
      _scrollToBottom();
    } finally {
      if (!mounted) return;
      setState(() {
        _isSending = false;
      });
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _startNewChat() {
    if (_messages.isEmpty) return;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Mulai obrolan baru?'),
        content: const Text(
          'Percakapan di layar akan dihapus. Riwayat tetap tersimpan untuk akun yang login.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Batal'),
          ),
          TextButton(
            onPressed: () {
              setState(() {
                _messages.clear();
                _currentSessionId = null;
              });
              Navigator.of(context).pop();
            },
            child: const Text('Mulai baru'),
          ),
        ],
      ),
    );
  }

  void _onExampleTap(String text) {
    setState(() {
      _controller.text = text;
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bool hasConversation = _messages.isNotEmpty;

    return Scaffold(
      backgroundColor: const Color(0xFF020617),
      appBar: AppBar(
        backgroundColor: const Color(0xFF020617),
        elevation: 4,
        titleSpacing: 0,
        title: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              margin: const EdgeInsets.only(right: 12),
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  colors: [Color(0xFFF97316), Color(0xFFEA580C)],
                ),
              ),
              child: const Icon(Icons.scale, color: Colors.white),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('HAI - Hukum AI'),
                Text(
                  _isLoggedIn
                      ? 'Asisten hukum lalu lintas • $_effectiveUsername'
                      : 'Asisten hukum lalu lintas (Guest)',
                  style: const TextStyle(fontSize: 12, color: Colors.white70),
                ),
              ],
            ),
          ],
        ),
        actions: [
          if (!_isLoggedIn)
            IconButton(
              tooltip: 'Login',
              onPressed: () {
                Navigator.pushNamed(context, '/login');
              },
              icon: const Icon(Icons.login),
            ),
          if (_isLoggedIn)
            IconButton(
              tooltip: 'Logout',
              onPressed: () {
                setState(() {
                  _username = null;
                  _currentSessionId = null;
                  _messages.clear();
                });
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Anda telah logout.')),
                );
              },
              icon: const Icon(Icons.logout),
            ),
          if (hasConversation)
            IconButton(
              tooltip: 'Obrolan baru',
              onPressed: _startNewChat,
              icon: const Icon(Icons.add),
            ),
          IconButton(
            tooltip: 'Riwayat',
            onPressed: () {
              if (!_isLoggedIn) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Login dulu untuk melihat riwayat konsultasi.'),
                  ),
                );
                return;
              }

              Navigator.pushNamed(
                context,
                '/history',
                arguments: {
                  'username': _effectiveUsername,
                },
              );
            },
            icon: const Icon(Icons.history),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: hasConversation ? _buildChatList() : _buildWelcomeScreen(),
          ),
          const Divider(height: 1, color: Color(0xFF1F2937)),
          _buildInputArea(),
        ],
      ),
    );
  }

  Widget _buildWelcomeScreen() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: SingleChildScrollView(
          child: Column(
            children: [
              Container(
                width: 80,
                height: 80,
                decoration: const BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: LinearGradient(
                    colors: [Color(0xFFF97316), Color(0xFFEA580C)],
                  ),
                ),
                child: const Icon(Icons.smart_toy, color: Colors.white, size: 40),
              ),
              const SizedBox(height: 16),
              const Text(
                'Asisten Hukum Lalu Lintas',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Tanyakan sesuatu tentang hukum lalu lintas dan saya akan membantu Anda.',
                style: TextStyle(color: Colors.white70),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'Contoh pertanyaan:',
                  style: TextStyle(color: Colors.white70),
                ),
              ),
              const SizedBox(height: 8),
              _exampleQuestionButton('Bagaimana prosedur mengurus SIM hilang?'),
              _exampleQuestionButton('Berapa denda untuk pelanggaran lampu merah?'),
              _exampleQuestionButton('Apa yang harus dilakukan saat kecelakaan?'),
            ],
          ),
        ),
      ),
    );
  }

  Widget _exampleQuestionButton(String text) {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      width: double.infinity,
      child: OutlinedButton(
        style: OutlinedButton.styleFrom(
          side: const BorderSide(color: Color(0xFF1F2937)),
          backgroundColor: const Color(0xFF020617),
          foregroundColor: Colors.white70,
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
        onPressed: () => _onExampleTap(text),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text(text),
        ),
      ),
    );
  }

  Widget _buildChatList() {
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.all(12),
      itemCount: _messages.length + (_isTyping ? 1 : 0),
      itemBuilder: (context, index) {
        if (_isTyping && index == _messages.length) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _avatar(isUser: false),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
                decoration: BoxDecoration(
                  color: const Color(0xFF111827),
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: const [
                    _TypingDot(),
                    SizedBox(width: 4),
                    _TypingDot(delay: 0.15),
                    SizedBox(width: 4),
                    _TypingDot(delay: 0.3),
                  ],
                ),
              ),
            ],
          );
        }

        final msg = _messages[index];
        final align = msg.isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start;
        final mainAlign = msg.isUser ? MainAxisAlignment.end : MainAxisAlignment.start;

        return Container(
          margin: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            mainAxisAlignment: mainAlign,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!msg.isUser) _avatar(isUser: false),
              if (!msg.isUser) const SizedBox(width: 8),
              Flexible(
                child: Column(
                  crossAxisAlignment: align,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 10,
                        horizontal: 14,
                      ),
                      decoration: BoxDecoration(
                        gradient: msg.isUser
                            ? const LinearGradient(
                                colors: [Color(0xFFF97316), Color(0xFFEA580C)],
                              )
                            : null,
                        color: msg.isUser ? null : const Color(0xFF111827),
                        borderRadius: BorderRadius.only(
                          topLeft: Radius.circular(msg.isUser ? 18 : 0),
                          topRight: Radius.circular(msg.isUser ? 0 : 18),
                          bottomLeft: const Radius.circular(18),
                          bottomRight: const Radius.circular(18),
                        ),
                        border: msg.isUser
                            ? null
                            : Border.all(color: const Color(0xFF1F2937)),
                      ),
                      child: Text(
                        msg.text,
                        style: const TextStyle(color: Colors.white),
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _formatTime(msg.timestamp),
                      style: const TextStyle(
                        fontSize: 11,
                        color: Colors.white54,
                      ),
                    ),
                  ],
                ),
              ),
              if (msg.isUser) const SizedBox(width: 8),
              if (msg.isUser) _avatar(isUser: true),
            ],
          ),
        );
      },
    );
  }

  String _formatTime(DateTime dt) {
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  Widget _avatar({required bool isUser}) {
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: LinearGradient(
          colors: isUser
              ? const [Color(0xFFF97316), Color(0xFFEA580C)]
              : const [Color(0xFF3B82F6), Color(0xFF2563EB)],
        ),
      ),
      child: Icon(
        isUser ? Icons.person : Icons.smart_toy,
        color: Colors.white,
        size: 18,
      ),
    );
  }

  Widget _buildInputArea() {
    return Container(
      color: const Color(0xFF020617),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              minLines: 1,
              maxLines: 4,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Ketik pertanyaan...',
                hintStyle: const TextStyle(color: Colors.white54),
                filled: true,
                fillColor: const Color(0xFF111827),
                contentPadding: const EdgeInsets.symmetric(
                  vertical: 10,
                  horizontal: 14,
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(999),
                  borderSide: const BorderSide(color: Color(0xFF1F2937)),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(999),
                  borderSide: const BorderSide(color: Color(0xFFF97316)),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          InkWell(
            onTap: _isSending ? null : _sendMessage,
            borderRadius: BorderRadius.circular(999),
            child: Container(
              width: 44,
              height: 44,
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  colors: [Color(0xFFF97316), Color(0xFFEA580C)],
                ),
              ),
              child: _isSending
                  ? const Padding(
                      padding: EdgeInsets.all(10),
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    )
                  : const Icon(Icons.send, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }
}

class _TypingDot extends StatefulWidget {
  final double delay;
  const _TypingDot({this.delay = 0, Key? key}) : super(key: key);

  @override
  State<_TypingDot> createState() => _TypingDotState();
}

class _TypingDotState extends State<_TypingDot> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final t = (_controller.value + widget.delay) % 1.0;
        final offset = t < 0.5 ? -4 * t * 2 : -4 * (1 - t) * 2;
        return Transform.translate(
          offset: Offset(0, offset),
          child: Container(
            width: 6,
            height: 6,
            decoration: const BoxDecoration(
              color: Colors.white54,
              shape: BoxShape.circle,
            ),
          ),
        );
      },
    );
  }
}