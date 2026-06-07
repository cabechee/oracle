import 'package:flutter/material.dart';

/// 홈 탭 — 비활성 placeholder (추후 채움).
class HomeTab extends StatelessWidget {
  const HomeTab({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.home_outlined,
                size: 56, color: Theme.of(context).disabledColor),
            const SizedBox(height: 12),
            Text('홈은 곧 채워질 예정이에요',
                style: TextStyle(color: Theme.of(context).disabledColor)),
          ],
        ),
      ),
    );
  }
}
