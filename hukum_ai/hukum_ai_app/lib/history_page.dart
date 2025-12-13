import 'package:flutter/material.dart';
import 'api_service.dart';

class HistoryPage extends StatefulWidget {
  final String username;

  const HistoryPage({
    super.key,
    required this.username,
  });

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  final ApiService _apiService = ApiService();

  bool _isLoading = true;
  String? _error;
  List<ChatSessionSummary> _history = [];

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final data = await _apiService.getChatHistory(widget.username);
      setState(() {
        _history = data;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = 'Gagal memuat riwayat: $e';
        _isLoading = false;
      });
    }
  }

  String _formatDateTime(String? raw) {
    if (raw == null || raw.isEmpty) return '';

    try {
      final dt = DateTime.parse(raw);
      final now = DateTime.now();
      final diffDays = now.difference(dt).inDays;

      String tanggal;
      if (diffDays == 0) {
        tanggal = 'Hari ini';
      } else if (diffDays == 1) {
        tanggal = 'Kemarin';
      } else if (diffDays < 7) {
        tanggal = '$diffDays hari yang lalu';
      } else {
        tanggal = '${dt.day} ${_bulan(dt.month)} ${dt.year}';
      }

      final h = dt.hour.toString().padLeft(2, '0');
      final m = dt.minute.toString().padLeft(2, '0');
      return '$tanggal, $h:$m';
    } catch (_) {
      return raw;
    }
  }

  String _bulan(int m) {
    const nama = [
      '',
      'Januari',
      'Februari',
      'Maret',
      'April',
      'Mei',
      'Juni',
      'Juli',
      'Agustus',
      'September',
      'Oktober',
      'November',
      'Desember'
    ];
    if (m < 1 || m > 12) return '';
    return nama[m];
  }

  void _openSessionDetail(ChatSessionSummary session) {
    Navigator.pushNamed(
      context,
      '/',
      arguments: {
        'initialSessionId': session.sessionId,
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF020617),
      appBar: AppBar(
        backgroundColor: const Color(0xFF020617),
        elevation: 4,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Riwayat Konsultasi',
              style: TextStyle(color: Colors.white),
            ),
            if (!_isLoading && _error == null)
              Text(
                '${_history.length} konsultasi',
                style: const TextStyle(color: Colors.white70, fontSize: 12),
              ),
          ],
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: CircularProgressIndicator(
          valueColor: AlwaysStoppedAnimation<Color>(Color(0xFFF97316)),
        ),
      );
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.error_outline, color: Colors.redAccent, size: 40),
            const SizedBox(height: 12),
            Text(
              _error!,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadHistory,
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFF97316),
              ),
              child: const Text('Coba Lagi'),
            ),
          ],
        ),
      );
    }

    if (_history.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: const Color(0xFF111827),
                borderRadius: BorderRadius.circular(32),
              ),
              child: const Icon(
                Icons.chat_bubble_outline,
                color: Colors.white54,
                size: 32,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'Belum Ada Riwayat',
              style: TextStyle(color: Colors.white, fontSize: 18),
            ),
            const SizedBox(height: 8),
            const Text(
              'Mulai konsultasi baru untuk melihat riwayat di sini.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.white70),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadHistory,
      color: const Color(0xFFF97316),
      child: ListView.separated(
        physics: const AlwaysScrollableScrollPhysics(),
        itemCount: _history.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (context, index) {
          final session = _history[index];
          final waktuText = _formatDateTime(session.createdAt);

          final titleText = session.title.trim().isEmpty
              ? 'Konsultasi #${session.sessionId}'
              : session.title.trim();

          return InkWell(
            onTap: () => _openSessionDetail(session),
            borderRadius: BorderRadius.circular(16),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF020617),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: const Color(0xFF1F2937)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 28,
                        height: 28,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(14),
                          gradient: const LinearGradient(
                            colors: [Color(0xFFF97316), Color(0xFFEA580C)],
                          ),
                        ),
                        child: const Icon(
                          Icons.message_rounded,
                          color: Colors.white,
                          size: 16,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          titleText,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  if (waktuText.isNotEmpty)
                    Row(
                      children: [
                        const Icon(
                          Icons.access_time,
                          size: 14,
                          color: Colors.white54,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          waktuText,
                          style: const TextStyle(
                            color: Colors.white54,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  const SizedBox(height: 8),
                  Text(
                    session.lastPreview ?? '(Belum ada percakapan)',
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}