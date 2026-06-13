import 'package:flutter/widgets.dart';

/// Phosphor Thin 아이콘 — 패키지(phosphor_flutter 2.1.0)가 최신 Flutter와
/// 비호환(IconData final class)이라 폰트만 번들하고 코드포인트를 직접 정의.
/// 추가 필요 시 phosphor_flutter 소스의 phosphor_icons_thin.dart에서 코드포인트 참조.
abstract final class PhosphorThin {
  static const _family = 'PhosphorThin';

  static const camera = IconData(0xe10e, fontFamily: _family);
  static const filmStrip = IconData(0xe792, fontFamily: _family);
  static const image = IconData(0xe2ca, fontFamily: _family);
  static const images = IconData(0xe836, fontFamily: _family);
  static const microphone = IconData(0xe326, fontFamily: _family);
  static const stop = IconData(0xe46c, fontFamily: _family);
  static const videoCamera = IconData(0xe4da, fontFamily: _family);
  static const x = IconData(0xe4f6, fontFamily: _family);
}
