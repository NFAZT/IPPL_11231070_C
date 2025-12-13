import 'package:flutter/material.dart';
import 'api_service.dart';

class PasswordRecoveryPage extends StatefulWidget {
  final VoidCallback? onBack;
  final ValueChanged<String>? onSubmit;
  final VoidCallback? onNavigateToReset;

  const PasswordRecoveryPage({
    Key? key,
    this.onBack,
    this.onSubmit,
    this.onNavigateToReset,
  }) : super(key: key);

  @override
  State<PasswordRecoveryPage> createState() => _PasswordRecoveryPageState();
}

class _PasswordRecoveryPageState extends State<PasswordRecoveryPage> {
  final TextEditingController _emailController = TextEditingController();
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  bool _isLoading = false;
  String? _infoMessage;
  String? _errorMessage;

  final _api = ApiService();

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _handleSubmit() async {
    if (!_formKey.currentState!.validate()) return;

    FocusScope.of(context).unfocus();

    final email = _emailController.text.trim();

    if (widget.onSubmit != null) {
      widget.onSubmit!(email);
      return;
    }

    setState(() {
      _isLoading = true;
      _infoMessage = null;
      _errorMessage = null;
    });

    try {
      final msg = await _api.forgotPassword(email);
      setState(() {
        _infoMessage = msg;
      });
    } catch (e) {
      setState(() {
        _errorMessage =
            'Gagal mengirim permintaan reset password. Coba lagi nanti.';
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF020617),
      appBar: AppBar(
        title: const Text('Lupa Password'),
        backgroundColor: const Color(0xFF020617),
        elevation: 0,
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Center(
          child: SingleChildScrollView(
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.center,
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
                    child: const Icon(
                      Icons.lock,
                      color: Colors.white,
                      size: 40,
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Lupa Password?',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                    ),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Masukkan email Anda untuk menerima token reset password.',
                    style: TextStyle(color: Colors.white70),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),

                  Container(
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.5),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    padding: const EdgeInsets.symmetric(
                      vertical: 20,
                      horizontal: 24,
                    ),
                    child: Column(
                      children: [
                        TextFormField(
                          controller: _emailController,
                          decoration: InputDecoration(
                            labelText: 'Email Terdaftar',
                            prefixIcon: const Icon(
                              Icons.email,
                              color: Colors.white70,
                            ),
                            labelStyle:
                                const TextStyle(color: Colors.white70),
                            fillColor: Colors.white10,
                            filled: true,
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          keyboardType: TextInputType.emailAddress,
                          style: const TextStyle(color: Colors.white),
                          validator: (value) {
                            final v = (value ?? '').trim();
                            if (v.isEmpty) {
                              return 'Email wajib diisi';
                            }
                            if (!v.contains('@')) {
                              return 'Format email tidak valid';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 20),
                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: _isLoading ? null : _handleSubmit,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFFF97316),
                              padding: const EdgeInsets.symmetric(
                                vertical: 15,
                                horizontal: 20,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                            child: _isLoading
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      valueColor:
                                          AlwaysStoppedAnimation(Colors.white),
                                    ),
                                  )
                                : const Text(
                                    'Kirim Token Reset',
                                    style: TextStyle(fontSize: 16),
                                  ),
                          ),
                        ),

                        const SizedBox(height: 8),

                        //pesan sukses/error
                        if (_infoMessage != null)
                          Text(
                            _infoMessage!,
                            style: const TextStyle(
                              color: Colors.greenAccent,
                              fontSize: 13,
                            ),
                            textAlign: TextAlign.center,
                          ),
                        if (_errorMessage != null)
                          Text(
                            _errorMessage!,
                            style: const TextStyle(
                              color: Colors.redAccent,
                              fontSize: 13,
                            ),
                            textAlign: TextAlign.center,
                          ),
                      ],
                    ),
                  ),

                  const SizedBox(height: 16),

                  //ke halaman reset
                  TextButton(
                    onPressed: widget.onNavigateToReset,
                    child: const Text(
                      'Sudah punya token? Reset password di sini',
                      style: TextStyle(color: Colors.orange),
                    ),
                  ),

                  const SizedBox(height: 16),

                  //ke login
                  TextButton(
                    onPressed: () {
                      if (widget.onBack != null) {
                        widget.onBack!();
                      } else {
                        Navigator.pop(context);
                      }
                    },
                    style: TextButton.styleFrom(
                      backgroundColor: Colors.orange[400],
                      padding: const EdgeInsets.symmetric(
                        vertical: 12,
                        horizontal: 24,
                      ),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    child: const Text(
                      'Kembali ke Login',
                      style: TextStyle(color: Colors.white),
                    ),
                  ),
                  const SizedBox(height: 16),

                  const Text(
                    'Tidak menerima email? Tunggu dalam beberapa saat.',
                    style: TextStyle(color: Colors.white70),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}