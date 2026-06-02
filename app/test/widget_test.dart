// 첫 슬라이스 placeholder — HomePage가 initState에서 API 호출하므로
// 실제 위젯 테스트는 백엔드 mock 도입 후. 지금은 analyze 통과용 stub.

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('placeholder', () {
    expect(1, 1);
  });
}
