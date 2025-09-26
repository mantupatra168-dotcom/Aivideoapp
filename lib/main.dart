import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import 'dart:io';

void main() {
  runApp(const AiVantuApp());
}

class AiVantuApp extends StatelessWidget {
  const AiVantuApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AiVantu',
      theme: ThemeData(primarySwatch: Colors.blue),
      home: const CreateVideoScreen(),
    );
  }
}

class CreateVideoScreen extends StatefulWidget {
  const CreateVideoScreen({super.key});

  @override
  State<CreateVideoScreen> createState() => _CreateVideoScreenState();
}

class _CreateVideoScreenState extends State<CreateVideoScreen> {
  final TextEditingController _scriptController = TextEditingController();
  String selectedTemplate = "Default";
  String selectedVoice = "Female";
  String? userVoicePath;
  List<String> selectedCharacters = [];
  String selectedMusic = "None";
  String selectedLength = "Short";
  String selectedQuality = "HD";
  String? downloadUrl;

  Future<void> pickCharacterPhotos() async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.image,
      allowMultiple: true,
    );
    if (result != null) {
      setState(() {
        selectedCharacters.addAll(result.paths.whereType<String>());
      });
    }
  }

  Future<void> pickUserVoice() async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.audio,
    );
    if (result != null && result.files.isNotEmpty) {
      setState(() {
        userVoicePath = result.files.first.path;
      });
    }
  }

  Future<void> submitVideo() async {
    var uri = Uri.parse("https://your-render-url.onrender.com/generate_video");

    var request = http.MultipartRequest("POST", uri);
    request.fields["script"] = _scriptController.text;
    request.fields["template"] = selectedTemplate;
    request.fields["voice"] = selectedVoice;
    request.fields["length"] = selectedLength;
    request.fields["quality"] = selectedQuality;

    if (userVoicePath != null) {
      request.files.add(await http.MultipartFile.fromPath("user_voice", userVoicePath!));
    }

    for (var photo in selectedCharacters) {
      request.files.add(await http.MultipartFile.fromPath("characters", photo));
    }

    var response = await request.send();
    if (response.statusCode == 200) {
      var body = await response.stream.bytesToString();
      setState(() {
        downloadUrl = "https://your-render-url.onrender.com/download/final_video.mp4";
      });

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("✅ Video generated successfully!")),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("❌ Error generating video")),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Create Video")),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _scriptController,
              maxLines: 5,
              decoration: const InputDecoration(
                hintText: "Write your script here...",
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 20),

            DropdownButton<String>(
              value: selectedTemplate,
              items: ["Default", "Promo", "Motivation", "Explainer", "Shorts"]
                  .map((t) => DropdownMenuItem(value: t, child: Text(t)))
                  .toList(),
              onChanged: (v) => setState(() => selectedTemplate = v!),
            ),

            DropdownButton<String>(
              value: selectedVoice,
              items: ["Female", "Male", "Child", "Celebrity"]
                  .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                  .toList(),
              onChanged: (v) => setState(() => selectedVoice = v!),
            ),

            ElevatedButton.icon(
              onPressed: pickUserVoice,
              icon: const Icon(Icons.mic),
              label: Text(userVoicePath == null ? "Upload Your Voice" : "Voice Selected"),
            ),

            ElevatedButton.icon(
              onPressed: pickCharacterPhotos,
              icon: const Icon(Icons.image),
              label: const Text("Upload Character Photos"),
            ),

            const SizedBox(height: 20),
            ElevatedButton.icon(
              onPressed: submitVideo,
              icon: const Icon(Icons.video_call),
              label: const Text("🎬 Generate Video"),
            ),

            if (downloadUrl != null) ...[
              const SizedBox(height: 20),
              Text("Download your video:"),
              SelectableText(downloadUrl!),
            ]
          ],
        ),
      ),
    );
  }
}
