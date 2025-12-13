import 'package:flutter/material.dart';

import 'home_page.dart';
import 'login_page.dart';
import 'register_page.dart';
import 'password_recovery_page.dart';
import 'history_page.dart';
import 'reset_password_page.dart';
import 'api_service.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final ApiService _api = ApiService();

  String? _loggedInUsername;

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFFF97316);

    return MaterialApp(
      title: 'HAI - Hukum AI',
      debugShowCheckedModeBanner: false,

      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF020617),
        colorScheme: ColorScheme.fromSeed(
          seedColor: seed,
          brightness: Brightness.dark,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF020617),
          elevation: 0,
          iconTheme: IconThemeData(color: Colors.white),
          titleTextStyle: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF111827),
          hintStyle: const TextStyle(color: Colors.white54),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: Color(0xFF1F2937)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: Color(0xFF1F2937)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: seed),
          ),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: seed,
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
          ),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(
            foregroundColor: seed,
          ),
        ),
      ),

      initialRoute: '/',

      routes: {
        //home
        '/': (context) => HomePage(
              username: _loggedInUsername,
            ),

        //login
        '/login': (context) => LoginPage(
              onLogin: (identifier, password) async {
                try {
                  final user = await _api.login(identifier, password);

                  setState(() {
                    _loggedInUsername = user.username;
                  });

                  if (!mounted) return;
                  Navigator.pushReplacementNamed(context, '/');
                } catch (e) {
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Login gagal: $e'),
                    ),
                  );
                }
              },
              onNavigateToRegister: () {
                Navigator.pushNamed(context, '/register');
              },
              onNavigateToRecovery: () {
                Navigator.pushNamed(context, '/password-recovery');
              },
              onContinueWithoutLogin: () {
                setState(() {
                  _loggedInUsername = null;
                });
                Navigator.pushReplacementNamed(context, '/');
              },
            ),

        //register
        '/register': (context) => RegisterPage(
              onRegister: (username, email, password) async {
                try {
                  await _api.register(username, email, password);

                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Registrasi berhasil, silakan login.'),
                    ),
                  );
                  Navigator.pushReplacementNamed(context, '/login');
                } catch (e) {
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Registrasi gagal: $e'),
                    ),
                  );
                }
              },
              onNavigateToLogin: () {
                Navigator.pushReplacementNamed(context, '/login');
              },
            ),

        //lupa password
        '/password-recovery': (context) => PasswordRecoveryPage(
              onBack: () {
                Navigator.pop(context);
              },
              onNavigateToReset: () {
                Navigator.pushNamed(context, '/reset-password');
              },
            ),

        //reset password
        '/reset-password': (context) => const ResetPasswordPage(),

        //history
        '/history': (context) {
          if (_loggedInUsername == null) {
            return Scaffold(
              appBar: AppBar(
                title: const Text('Riwayat Konsultasi'),
              ),
              body: const Center(
                child: Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    'Riwayat hanya tersedia untuk pengguna yang sudah login.',
                    textAlign: TextAlign.center,
                  ),
                ),
              ),
            );
          }

          return HistoryPage(
            username: _loggedInUsername!,
          );
        },
      },
    );
  }
}