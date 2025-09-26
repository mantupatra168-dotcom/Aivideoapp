import 'dart:io';
import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:video_player/video_player.dart';
import 'package:chewie/chewie.dart';

void main() {
  runApp(const AiVantuApp());
}

class AiVantuApp extends StatelessWidget {
  const AiVantuApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: "AiVantu",
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

const String backendBase = "https://YOUR-BACKEND-URL.onrender.com";

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("AiVantu Video App")),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            ElevatedButton(
                onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const GenerateVideoScreen())),
                child: const Text("🎬 Generate Video")),
            ElevatedButton(
                onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const GalleryScreen())),
                child: const Text("📂 Gallery")),
            ElevatedButton(
                onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const PlansScreen())),
                child: const Text("💳 Plans")),
            ElevatedButton(
                onPressed: () => Navigator.push(
                    context,
                    MaterialPageRoute(builder: (_) => const ProfileScreen())),
                child: const Text("👤 Profile")),
          ],
        ),
      ),
    );
  }
}

class GenerateVideoScreen extends StatefulWidget {
  const GenerateVideoScreen({super.key});
  @override
  State<GenerateVideoScreen> createState() => _GenerateVideoScreenState();
}

class _GenerateVideoScreenState extends State<GenerateVideoScreen> {
  final _scriptCtrl = TextEditingController();
  File? characterImage;
  bool loading = false;
  String? videoUrl;

  Future<void> _pickImage() async {
    final result = await FilePicker.platform.pickFiles(type: FileType.image);
    if (result != null) {
      setState(() {
        characterImage = File(result.files.single.path!);
      });
    }
  }

  Future<void> _generateVideo() async {
    if (characterImage == null || _scriptCtrl.text.isEmpty) return;

    setState(() => loading = true);
    try {
      final formData = FormData.fromMap({
        "user_email": "demo@aivantu.com",
        "title": "Flutter Test Video",
        "script": _scriptCtrl.text,
        "quality": "HD",
        "lang": "hi",
        "characters": await MultipartFile.fromFile(characterImage!.path,
            filename: "char.png"),
      });

      final res = await Dio().post("$backendBase/generate_video",
          data: formData,
          options: Options(contentType: "multipart/form-data"));

      if (res.data["status"] == "done") {
        setState(() {
          videoUrl = res.data["download_url"];
        });
      }
    } catch (e) {
      debugPrint("Error: $e");
    }
    setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Generate Video")),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _scriptCtrl,
              decoration: const InputDecoration(
                  labelText: "Enter Script", border: OutlineInputBorder()),
              maxLines: 3,
            ),
            const SizedBox(height: 12),
            ElevatedButton(
                onPressed: _pickImage,
                child: Text(characterImage == null
                    ? "Pick Character Image"
                    : "✅ Image Selected")),
            const SizedBox(height: 12),
            ElevatedButton(
                onPressed: loading ? null : _generateVideo,
                child: loading
                    ? const CircularProgressIndicator()
                    : const Text("Generate")),
            const SizedBox(height: 20),
            if (videoUrl != null) Expanded(child: VideoPlayerWidget(url: videoUrl!)),
          ],
        ),
      ),
    );
  }
}

class VideoPlayerWidget extends StatefulWidget {
  final String url;
  const VideoPlayerWidget({super.key, required this.url});

  @override
  State<VideoPlayerWidget> createState() => _VideoPlayerWidgetState();
}

class _VideoPlayerWidgetState extends State<VideoPlayerWidget> {
  late VideoPlayerController _controller;
  ChewieController? _chewieController;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.networkUrl(Uri.parse(widget.url))
      ..initialize().then((_) {
        _chewieController =
            ChewieController(videoPlayerController: _controller, autoPlay: true, looping: false);
        setState(() {});
      });
  }

  @override
  void dispose() {
    _controller.dispose();
    _chewieController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _chewieController != null &&
            _chewieController!.videoPlayerController.value.isInitialized
        ? Chewie(controller: _chewieController!)
        : const Center(child: CircularProgressIndicator());
  }
}

class GalleryScreen extends StatelessWidget {
  const GalleryScreen({super.key});

  Future<List<dynamic>> _fetchVideos() async {
    final res = await Dio().get("$backendBase/outputs");
    return res.data is List ? res.data : [];
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
        appBar: AppBar(title: const Text("Gallery")),
        body: FutureBuilder(
            future: _fetchVideos(),
            builder: (c, snap) {
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              final vids = snap.data as List;
              return ListView.builder(
                  itemCount: vids.length,
                  itemBuilder: (_, i) => ListTile(title: Text(vids[i].toString())));
            }));
  }
}

class PlansScreen extends StatelessWidget {
  const PlansScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
        appBar: AppBar(title: const Text("Plans")),
        body: ListView(children: const [
          ListTile(title: Text("Free Plan - ₹0")),
          ListTile(title: Text("Premium - ₹499/month")),
          ListTile(title: Text("Pro - ₹999/month")),
        ]));
  }
}

class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
        appBar: AppBar(title: const Text("Profile")),
        body: const Center(child: Text("Demo User (Plan: Free)")));
  }
}
