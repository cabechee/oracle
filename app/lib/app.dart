import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/design.dart';
import 'features/home/home_page.dart';

class OracleApp extends StatelessWidget {
  const OracleApp({super.key});
  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: OracleColors.vermilion,
      surface: OracleColors.paper,
      onSurface: OracleColors.ink,
    );
    return MaterialApp(
      title: 'Oracle',
      // 한국어 우선 — showDatePicker 등 머티리얼 위젯 한글화
      locale: const Locale('ko'),
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('ko'), Locale('en')],
      // 종이 디자인은 라이트 단일 — 다크는 추후 "필름 모드"로 별도 설계
      themeMode: ThemeMode.light,
      theme: ThemeData(
        colorScheme: scheme.copyWith(
          primary: OracleColors.vermilion,
          outlineVariant: OracleColors.hairline,
        ),
        useMaterial3: true,
        fontFamily: OracleType.sans,
        scaffoldBackgroundColor: OracleColors.paper,
        appBarTheme: const AppBarTheme(
          backgroundColor: OracleColors.paper,
          foregroundColor: OracleColors.ink,
          elevation: 0,
          scrolledUnderElevation: 0,
          titleTextStyle: TextStyle(
            fontFamily: OracleType.meta,
            fontSize: 15,
            color: OracleColors.ink,
            fontVariations: [FontVariation('opsz', 12), FontVariation('wght', 300)],
          ),
        ),
        tabBarTheme: const TabBarThemeData(
          labelColor: OracleColors.ink,
          unselectedLabelColor: OracleColors.faint,
          indicatorColor: OracleColors.vermilion,
          dividerColor: OracleColors.hairline,
          labelStyle: TextStyle(
            fontFamily: OracleType.sans,
            fontSize: 12,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.3,
          ),
          unselectedLabelStyle: TextStyle(
            fontFamily: OracleType.sans,
            fontSize: 12,
            letterSpacing: 0.3,
          ),
        ),
        dividerTheme: const DividerThemeData(
          color: OracleColors.hairline,
          thickness: 0.5,
          space: 0.5,
        ),
        snackBarTheme: SnackBarThemeData(
          backgroundColor: OracleColors.ink,
          contentTextStyle: const TextStyle(
            fontFamily: OracleType.sans,
            fontSize: 12.5,
            color: OracleColors.paper,
          ),
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
        ),
        progressIndicatorTheme:
            const ProgressIndicatorThemeData(color: OracleColors.vermilion),
      ),
      home: const HomePage(),
    );
  }
}
