import 'package:flutter/material.dart';

import 'api.dart';
import 'models.dart';

/// LLM 선택 모달. 반환값:
/// - null: 사용자 취소
/// - "": "서버 디폴트" 선택 (.env TASK_ALIAS 사용)
/// - 그 외: 선택된 Nest alias
Future<String?> showLlmPicker(
  BuildContext context,
  OracleApi api,
  String? current,
) {
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (_) => _LlmPickerSheet(api: api, current: current),
  );
}

class _LlmPickerSheet extends StatefulWidget {
  final OracleApi api;
  final String? current;
  const _LlmPickerSheet({required this.api, required this.current});

  @override
  State<_LlmPickerSheet> createState() => _LlmPickerSheetState();
}

class _LlmPickerSheetState extends State<_LlmPickerSheet> {
  LlmCatalog? _catalog;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final c = await widget.api.listLlmModels();
      if (mounted) setState(() => _catalog = c);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final isLoading = _catalog == null && _error == null;
    final cur = widget.current;

    return SafeArea(
      top: false,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.75,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
              child: Text(
                'LLM 선택',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const Divider(height: 1),
            Flexible(
              child: () {
                if (isLoading) {
                  return const Center(
                    child: Padding(
                      padding: EdgeInsets.symmetric(vertical: 32),
                      child: CircularProgressIndicator(),
                    ),
                  );
                }
                if (_error != null) {
                  return Padding(
                    padding: const EdgeInsets.all(20),
                    child: Text('목록 로드 실패: $_error',
                        style: TextStyle(color: cs.error)),
                  );
                }
                final c = _catalog!;
                return ListView(
                  shrinkWrap: true,
                  children: [
                    // 자동 — env 명시 없으면 Nest enabled 첫 모델 (동적)
                    ListTile(
                      leading: const Icon(Icons.auto_awesome),
                      title: const Text('자동'),
                      subtitle: const Text(
                        '.env 명시 없으면 Nest 등록된 enabled 첫 모델 (동적)',
                      ),
                      trailing: cur == null
                          ? Icon(Icons.check, color: cs.primary)
                          : null,
                      onTap: () => Navigator.pop(context, ''),
                    ),
                    const Divider(height: 1),
                    // 개별 모델
                    for (final m in c.models)
                      ListTile(
                        leading: Icon(
                          m.tier == 'local'
                              ? Icons.home_outlined
                              : Icons.cloud_outlined,
                          color: cs.primary,
                        ),
                        title: Row(
                          children: [
                            Text(m.name),
                            const SizedBox(width: 6),
                            if (m.vision)
                              Tooltip(
                                message: 'Vision 지원',
                                child: Icon(
                                  Icons.visibility_outlined,
                                  size: 14,
                                  color: cs.outline,
                                ),
                              ),
                          ],
                        ),
                        subtitle: Text(_modelSubtitle(m)),
                        trailing: cur == m.alias
                            ? Icon(Icons.check, color: cs.primary)
                            : null,
                        onTap: () => Navigator.pop(context, m.alias),
                      ),
                    // Council (다중 모델 합성)
                    if (c.councils.isNotEmpty) ...[
                      const Divider(height: 1),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                        child: Text(
                          'Council (다중 모델 합성)',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                                color: cs.outline,
                              ),
                        ),
                      ),
                      for (final cc in c.councils)
                        ListTile(
                          leading: const Icon(Icons.groups_outlined),
                          title: Text(cc.name),
                          subtitle: Text(
                            '${cc.alias} · ${cc.members.join(" + ")}'
                            '${cc.chairAlias != null ? " · chair=${cc.chairAlias}" : ""}',
                          ),
                          trailing: cur == cc.alias
                              ? Icon(Icons.check, color: cs.primary)
                              : null,
                          onTap: () => Navigator.pop(context, cc.alias),
                        ),
                    ],
                    const SizedBox(height: 12),
                  ],
                );
              }(),
            ),
          ],
        ),
      ),
    );
  }

  String _modelSubtitle(LlmModel m) {
    final parts = <String>[m.alias];
    if (m.provider != null) parts.add(m.provider!);
    if (m.type != null) parts.add(m.type!);
    if (m.effort != null) parts.add('effort:${m.effort!}');
    if (m.tier != null) parts.add(m.tier!);
    return parts.join(' · ');
  }
}
