import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

typedef OnSubmit = Future<void> Function(String? comment, File? imageFile);

class ChatInput extends StatefulWidget {
  final OnSubmit onSubmit;
  const ChatInput({super.key, required this.onSubmit});

  @override
  State<ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<ChatInput> {
  final _ctrl = TextEditingController();
  final _picker = ImagePicker();
  File? _picked;
  bool _busy = false;

  Future<void> _pickFromCamera() async {
    try {
      final x = await _picker.pickImage(
        source: ImageSource.camera,
        imageQuality: 90,
      );
      if (x != null) setState(() => _picked = File(x.path));
    } catch (e) {
      _snack('카메라 실패: $e');
    }
  }

  Future<void> _pickFromGallery() async {
    try {
      final x = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 90,
      );
      if (x != null) setState(() => _picked = File(x.path));
    } catch (e) {
      _snack('갤러리 실패: $e');
    }
  }

  void _snack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _submit() async {
    final text = _ctrl.text.trim();
    if (text.isEmpty && _picked == null) return;
    setState(() => _busy = true);
    try {
      await widget.onSubmit(text.isEmpty ? null : text, _picked);
      if (!mounted) return;
      _ctrl.clear();
      setState(() => _picked = null);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surface,
          border: Border(
            top: BorderSide(color: Theme.of(context).dividerColor),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_picked != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(8),
                      child: Image.file(
                        _picked!,
                        width: 64,
                        height: 64,
                        fit: BoxFit.cover,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _picked!.path.split('/').last,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      onPressed: _busy
                          ? null
                          : () => setState(() => _picked = null),
                    ),
                  ],
                ),
              ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                IconButton(
                  icon: const Icon(Icons.photo_camera_outlined),
                  onPressed: _busy ? null : _pickFromCamera,
                  tooltip: '카메라',
                ),
                IconButton(
                  icon: const Icon(Icons.photo_library_outlined),
                  onPressed: _busy ? null : _pickFromGallery,
                  tooltip: '갤러리',
                ),
                Expanded(
                  child: TextField(
                    controller: _ctrl,
                    decoration: const InputDecoration(
                      hintText: '오늘 뭐든 던져봐...',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    minLines: 1,
                    maxLines: 5,
                    textInputAction: TextInputAction.newline,
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  icon: _busy
                      ? const SizedBox(
                          width: 22,
                          height: 22,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.send),
                  onPressed: _busy ? null : _submit,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
