import 'package:flutter/material.dart';

import 'features/home/home_page.dart';

class OracleApp extends StatelessWidget {
  const OracleApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Oracle',
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: Colors.blue,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}
