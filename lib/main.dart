import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_storage/firebase_storage.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:video_player/video_player.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();
  runApp(AiVantuApp());
}

class AiVantuApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AiVantu',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(),
      home: AuthGate(),
    );
  }
}

/// -------- AUTH GATE ----------
class AuthGate extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return StreamBuilder<User?>(
      stream: FirebaseAuth.instance.authStateChanges(),
      builder: (_, snapshot) {
        if (snapshot.hasData) {
          return HomeScreen();
        } else {
          return LoginScreen();
        }
      },
    );
  }
}

/// -------- LOGIN ----------
class LoginScreen extends StatelessWidget {
  Future<UserCredential> signInWithGoogle() async {
    final googleUser = await GoogleSignIn().signIn();
    final googleAuth = await googleUser!.authentication;
    final credential = GoogleAuthProvider.credential(
      accessToken: googleAuth.accessToken,
      idToken: googleAuth.idToken,
    );
    return await FirebaseAuth.instance.signInWithCredential(credential);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ElevatedButton.icon(
          icon: Icon(Icons.login),
          label: Text("Login with Google"),
          onPressed: () async {
            await signInWithGoogle();
          },
        ),
      ),
    );
  }
}

/// -------- HOME ----------
class HomeScreen extends StatefulWidget {
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _bottomIndex = 0;
  final backendBase = "https://p6.onrender.com"; // Flask backend

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser!;
    final tabs = [
      _buildHome(context),
      GalleryScreen(userEmail: user.email!),
      Center(child: Text("Images coming soon")),
      ProfileScreen(user: user),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text("AiVantu"),
      ),
      drawer: AppDrawer(user: user),
      body: tabs[_bottomIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _bottomIndex,
        onTap: (i) => setState(() => _bottomIndex = i),
        items: [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: "Home"),
          BottomNavigationBarItem(icon: Icon(Icons.video_call), label: "Videos"),
          BottomNavigationBarItem(icon: Icon(Icons.image), label: "Images"),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: "Profile"),
        ],
      ),
    );
  }

  Widget _buildHome(BuildContext context) {
    return Center(
      child: Column(
        children: [
          SizedBox(height: 20),
          ElevatedButton.icon(
            icon: Icon(Icons.image),
            label: Text("Upload & Generate Video"),
            onPressed: () async {
              await _generateVideo(context);
            },
          ),
          SizedBox(height: 20),
          ElevatedButton.icon(
            icon: Icon(Icons.assistant),
            label: Text("Ask Assistant"),
            onPressed: () async {
              await _askAssistant(context);
            },
          ),
        ],
      ),
    );
  }

  Future<void> _generateVideo(BuildContext context) async {
    final result = await FilePicker.platform.pickFiles(type: FileType.image);
    if (result == null) return;
    final file = File(result.files.single.path!);

    final uri = Uri.parse("$backendBase/generate_video");
    final request = http.MultipartRequest("POST", uri);
    request.fields["script"] = "Hello world from AiVantu!";
    request.fields["user_email"] = FirebaseAuth.instance.currentUser!.email!;
    request.fields["lang"] = "en";
    request.files.add(await http.MultipartFile.fromPath("characters", file.path));

    final resp = await request.send();
    final body = await resp.stream.bytesToString();
    final data = jsonDecode(body);

    if (data["status"] == "done") {
      final url = data["download_url"];

      // Save video URL in Firebase Storage
      try {
        final videoResp = await http.get(Uri.parse(url));
        final ref = FirebaseStorage.instance
            .ref()
            .child("videos/${FirebaseAuth.instance.currentUser!.uid}/${DateTime.now().millisecondsSinceEpoch}.mp4");
        await ref.putData(videoResp.bodyBytes);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Video saved to gallery ✅")),
        );
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Upload failed: $e")),
        );
      }
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Video generation failed!")),
      );
    }
  }

  Future<void> _askAssistant(BuildContext context) async {
    final uri = Uri.parse("$backendBase/assistant");
    final resp = await http.post(uri,
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"query": "How to improve my script?", "lang": "en"}));
    final data = jsonDecode(resp.body);

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text("Assistant: ${data["reply"]}")),
    );
  }
}

/// -------- GALLERY (Firebase Storage Videos) ----------
class GalleryScreen extends StatelessWidget {
  final String userEmail;
  GalleryScreen({required this.userEmail});

  @override
  Widget build(BuildContext context) {
    final uid = FirebaseAuth.instance.currentUser!.uid;
    final ref = FirebaseStorage.instance.ref().child("videos/$uid");

    return FutureBuilder<ListResult>(
      future: ref.listAll(),
      builder: (_, snapshot) {
        if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
        final items = snapshot.data!.items;
        if (items.isEmpty) return Center(child: Text("No videos yet."));
        return ListView.builder(
          itemCount: items.length,
          itemBuilder: (_, i) {
            final item = items[i];
            return FutureBuilder<String>(
              future: item.getDownloadURL(),
              builder: (_, snap) {
                if (!snap.hasData) return ListTile(title: Text("Loading..."));
                final url = snap.data!;
                return ListTile(
                  leading: Icon(Icons.play_circle_fill),
                  title: Text(item.name),
                  onTap: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => VideoPlayerScreen(videoUrl: url),
                      ),
                    );
                  },
                );
              },
            );
          },
        );
      },
    );
  }
}

/// -------- VIDEO PLAYER ----------
class VideoPlayerScreen extends StatefulWidget {
  final String videoUrl;
  VideoPlayerScreen({required this.videoUrl});
  @override
  _VideoPlayerScreenState createState() => _VideoPlayerScreenState();
}

class _VideoPlayerScreenState extends State<VideoPlayerScreen> {
  late VideoPlayerController _controller;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.network(widget.videoUrl)
      ..initialize().then((_) {
        setState(() {});
        _controller.play();
      });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text("Video Player")),
      body: Center(
        child: _controller.value.isInitialized
            ? AspectRatio(
                aspectRatio: _controller.value.aspectRatio,
                child: VideoPlayer(_controller),
              )
            : CircularProgressIndicator(),
      ),
    );
  }
}

/// -------- PROFILE ----------
class ProfileScreen extends StatelessWidget {
  final User user;
  ProfileScreen({required this.user});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          CircleAvatar(
              backgroundImage: NetworkImage(user.photoURL ?? ""), radius: 40),
          SizedBox(height: 12),
          Text(user.displayName ?? "User"),
          Text(user.email ?? ""),
        ],
      ),
    );
  }
}

/// -------- DRAWER ----------
class AppDrawer extends StatelessWidget {
  final User user;
  AppDrawer({required this.user});

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: ListView(
        children: [
          UserAccountsDrawerHeader(
            accountName: Text(user.displayName ?? "User"),
            accountEmail: Text(user.email ?? ""),
            currentAccountPicture: CircleAvatar(
              backgroundImage: NetworkImage(user.photoURL ?? ""),
            ),
          ),
          ListTile(
            leading: Icon(Icons.credit_score),
            title: Text("Credits"),
            onTap: () {},
          ),
          ListTile(
            leading: Icon(Icons.help),
            title: Text("Help Center"),
            onTap: () {},
          ),
          ListTile(
            leading: Icon(Icons.logout),
            title: Text("Sign Out"),
            onTap: () async {
              await FirebaseAuth.instance.signOut();
            },
          ),
        ],
      ),
    );
  }
}
