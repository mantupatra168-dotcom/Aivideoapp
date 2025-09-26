// lib/main.dart
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:fluttertoast/fluttertoast.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';

void main() {
  runApp(AiVantuApp());
}

const String API_BASE = "https://aivideoapp-kzp6.onrender.com";
class AiVantuApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AiVantu',
      theme: ThemeData(
        primarySwatch: Colors.indigo,
        visualDensity: VisualDensity.adaptivePlatformDensity,
      ),
      home: RootShell(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class RootShell extends StatefulWidget {
  @override
  _RootShellState createState() => _RootShellState();
}

class _RootShellState extends State<RootShell> {
  int _index = 0;
  final _pages = [
    DashboardPage(),
    CreatePage(),
    GalleryPage(),
    ProfilePage(),
    AssistantPage(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _pages[_index],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _index,
        onTap: (i) => setState(() => _index = i),
        items: [
          BottomNavigationBarItem(icon: Icon(Icons.home), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.create), label: 'Create'),
          BottomNavigationBarItem(icon: Icon(Icons.video_library), label: 'Gallery'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Profile'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'Assistant'),
        ],
        selectedItemColor: Colors.indigo,
        unselectedItemColor: Colors.grey[600],
        type: BottomNavigationBarType.fixed,
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => setState(() => _index = 1),
        child: Icon(Icons.add),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.centerDocked,
    );
  }
}

//////////////////////////////////////////////////////////////
/// Dashboard Page - show stats + quick actions
//////////////////////////////////////////////////////////////
class DashboardPage extends StatefulWidget {
  @override
  _DashboardPageState createState() => _DashboardPageState();
}
class _DashboardPageState extends State<DashboardPage> {
  bool loading = false;
  int totalVideos = 0;
  @override
  void initState() {
    super.initState();
    _fetchStats();
  }

  Future<void> _fetchStats() async {
    setState(() => loading = true);
    try {
      // Example: fetch gallery count
      final resp = await http.get(Uri.parse('$API_BASE/health'));
      if (resp.statusCode == 200) {
        // health check; for demo we keep totalVideos static
        setState(() {
          totalVideos = 0; // later call /dashboard endpoint to get real
        });
      } else {
        Fluttertoast.showToast(msg: "Server not ready");
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Network error");
    } finally {
      setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.all(14),
        child: ListView(
          children: [
            Row(
              children: [
                CircleAvatar(child: Icon(Icons.videocam), radius: 28),
                SizedBox(width: 12),
                Expanded(child: Text("AiVantu", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold))),
                ElevatedButton.icon(
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CreatePage())),
                  icon: Icon(Icons.add),
                  label: Text("Create"),
                )
              ],
            ),
            SizedBox(height: 16),
            Card(
              child: Padding(
                padding: EdgeInsets.all(12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text("Total Videos", style: TextStyle(color: Colors.grey[700])),
                      SizedBox(height:6),
                      Text("$totalVideos", style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
                    ]),
                    ElevatedButton.icon(
                      onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => GalleryPage())),
                      icon: Icon(Icons.video_library),
                      label: Text("My Gallery"),
                    )
                  ],
                ),
              ),
            ),
            SizedBox(height: 12),
            Text("Quick Actions", style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            SizedBox(height: 8),
            Wrap(
              spacing: 8, runSpacing: 8,
              children: [
                _ActionCard(icon: Icons.headphones, label: "Preview Voice", onTap: () => _previewVoiceDialog()),
                _ActionCard(icon: Icons.music_note, label: "BG Music", onTap: () => Fluttertoast.showToast(msg: "Open Create -> BG music")),
                _ActionCard(icon: Icons.trending_up, label: "Trending", onTap: () => Fluttertoast.showToast(msg: "Trending coming soon")),
                _ActionCard(icon: Icons.settings, label: "Settings", onTap: () => Fluttertoast.showToast(msg: "Settings coming soon")),
              ],
            ),
          ],
        ),
      ),
    );
  }

  void _previewVoiceDialog() {
    showDialog(context: context, builder: (_) => PreviewVoiceDialog());
  }
}

class _ActionCard extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _ActionCard({required this.icon, required this.label, required this.onTap});
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 150,
        padding: EdgeInsets.all(12),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(12), color: Colors.grey[50], border: Border.all(color: Colors.grey[200]!)),
        child: Column(children: [Icon(icon, size:28, color: Colors.indigo), SizedBox(height: 8), Text(label)]),
      ),
    );
  }
}

//////////////////////////////////////////////////////////////
/// Create Page - main form + upload + render
//////////////////////////////////////////////////////////////
class CreatePage extends StatefulWidget {
  @override
  _CreatePageState createState() => _CreatePageState();
}
class _CreatePageState extends State<CreatePage> {
  final _titleCtrl = TextEditingController();
  final _scriptCtrl = TextEditingController();
  String? selectedTemplate;
  List<String> templates = [];
  List<String> voices = [];
  List<XFile> characterImages = [];
  List<PlatformFile> characterVoiceFiles = [];
  File? bgMusicFile;
  String selectedQuality = "HD";
  String selectedLength = "short";
  String selectedLang = "hi"; // default Hindi per request
  bool rendering = false;

  @override
  void initState() {
    super.initState();
    _loadTemplates();
    _loadVoices();
  }

  Future<void> _loadTemplates() async {
    try {
      final resp = await http.get(Uri.parse('$API_BASE/templates')); // backend should expose endpoint (adjust)
      if (resp.statusCode == 200) {
        final data = json.decode(resp.body);
        // expect list of {name,category}
        setState(() {
          templates = List<String>.from(data.map((t) => t['name']));
          if (templates.isNotEmpty) selectedTemplate = templates.first;
        });
      } else {
        // fallback set
        setState(() {
          templates = ["Motivation", "Promo", "Explainer", "Cinematic"];
          selectedTemplate = templates.first;
        });
      }
    } catch (e) {
      setState(() {
        templates = ["Motivation", "Promo", "Explainer", "Cinematic"];
        selectedTemplate = templates.first;
      });
    }
  }

  Future<void> _loadVoices() async {
    try {
      final resp = await http.get(Uri.parse('$API_BASE/voices'));
      if (resp.statusCode == 200) {
        final data = json.decode(resp.body);
        setState(() {
          voices = List<String>.from(data.map((v) => v['display_name']));
        });
      } else {
        voices = ["Female","Male","Child","Celebrity"];
      }
    } catch (e) {
      voices = ["Female","Male","Child","Celebrity"];
    }
  }

  Future<void> _pickCharacterImages() async {
    try {
      final ImagePicker picker = ImagePicker();
      final List<XFile>? files = await picker.pickMultiImage(imageQuality: 85);
      if (files != null && files.isNotEmpty) {
        setState(() => characterImages.addAll(files));
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Image pick failed");
    }
  }

  Future<void> _pickCharacterVoices() async {
    try {
      FilePickerResult? res = await FilePicker.platform.pickFiles(allowMultiple: true, type: FileType.audio);
      if (res != null) {
        setState(() => characterVoiceFiles.addAll(res.files));
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Voice pick failed");
    }
  }

  Future<void> _pickBgMusic() async {
    try {
      FilePickerResult? res = await FilePicker.platform.pickFiles(type: FileType.audio);
      if (res != null && res.files.isNotEmpty) {
        setState(() => bgMusicFile = File(res.files.first.path!));
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Music pick failed");
    }
  }

  Future<void> _submitRender() async {
    if (rendering) return;
    final title = _titleCtrl.text.trim().isEmpty ? "Untitled" : _titleCtrl.text.trim();
    final script = _scriptCtrl.text.trim();
    if (characterImages.isEmpty && script.isEmpty) {
      Fluttertoast.showToast(msg: "Add script or at least one character image");
      return;
    }
    setState(() => rendering = true);

    try {
      var uri = Uri.parse('$API_BASE/generate_video');
      var req = http.MultipartRequest('POST', uri);
      req.fields['user_email'] = "demo@aivantu.com";
      req.fields['title'] = title;
      req.fields['script'] = script;
      req.fields['template'] = selectedTemplate ?? "Default";
      req.fields['quality'] = selectedQuality;
      req.fields['length_type'] = selectedLength;
      req.fields['lang'] = selectedLang;

      // add images
      for (int i=0;i<characterImages.length;i++) {
        final img = characterImages[i];
        var bytes = await img.readAsBytes();
        req.files.add(http.MultipartFile.fromBytes('characters', bytes, filename: img.name));
      }

      // add char voice files (if any)
      for (final vf in characterVoiceFiles) {
        final path = vf.path!;
        req.files.add(await http.MultipartFile.fromPath('character_voice_files', path));
      }

      // bg music file
      if (bgMusicFile != null) {
        req.files.add(await http.MultipartFile.fromPath('bg_music_file', bgMusicFile!.path));
      }

      // send request and listen
      final streamed = await req.send();
      final respStr = await streamed.stream.bytesToString();
      if (streamed.statusCode == 200 || streamed.statusCode == 201) {
        final jsonResp = json.decode(respStr);
        final download = jsonResp['download_url'] ?? jsonResp['video_url'];
        Fluttertoast.showToast(msg: "Render complete!");
        if (download != null) {
          // show link dialog
          showDialog(context: context, builder: (_) => DownloadDialog(url: download));
        }
      } else {
        Fluttertoast.showToast(msg: "Render failed: ${streamed.statusCode}");
        debugPrint(respStr);
      }
    } catch (e, st) {
      debugPrint("$e\n$st");
      Fluttertoast.showToast(msg: "Render request failed");
    } finally {
      setState(() => rendering = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Scaffold(
        appBar: AppBar(title: Text("Create Video")),
        body: SingleChildScrollView(
          padding: EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(controller: _titleCtrl, decoration: InputDecoration(labelText: "Title")),
              SizedBox(height: 10),
              TextField(controller: _scriptCtrl, decoration: InputDecoration(labelText: "Script"), maxLines: 6),
              SizedBox(height: 10),
              DropdownButtonFormField<String>(
                value: selectedTemplate,
                items: templates.map((t) => DropdownMenuItem(value: t, child: Text(t))).toList(),
                onChanged: (v) => setState(()=>selectedTemplate=v),
                decoration: InputDecoration(labelText: "Template"),
              ),
              SizedBox(height: 10),
              Text("Voices (choose styles)"),
              Wrap(
                spacing: 8,
                children: voices.map((v) => ChoiceChip(label: Text(v), selected: false, onSelected: (_){})).toList(),
              ),
              SizedBox(height: 12),
              Row(children: [
                ElevatedButton.icon(onPressed: _pickCharacterImages, icon: Icon(Icons.image), label: Text("Add Characters")),
                SizedBox(width: 8),
                ElevatedButton.icon(onPressed: _pickCharacterVoices, icon: Icon(Icons.mic), label: Text("Add Voices")),
              ]),
              SizedBox(height: 8),
              _buildSelectedFilesPreview(),
              SizedBox(height: 10),
              Row(children: [
                ElevatedButton.icon(onPressed: _pickBgMusic, icon: Icon(Icons.music_note), label: Text("Add BG Music")),
                SizedBox(width: 12),
                DropdownButton<String>(
                  value: selectedQuality,
                  items: ["HD","FULLHD","4K"].map((q)=>DropdownMenuItem(value:q,child:Text(q))).toList(),
                  onChanged: (v)=>setState(()=>selectedQuality=v!),
                ),
                SizedBox(width: 12),
                DropdownButton<String>(
                  value: selectedLength,
                  items: ["short","long"].map((q)=>DropdownMenuItem(value:q,child:Text(q))).toList(),
                  onChanged: (v)=>setState(()=>selectedLength=v!),
                ),
              ]),
              SizedBox(height: 14),
              Row(children: [
                ElevatedButton.icon(
                  onPressed: rendering ? null : _submitRender,
                  icon: rendering ? SizedBox(width:16,height:16,child:CircularProgressIndicator(strokeWidth:2)) : Icon(Icons.cloud_upload),
                  label: Text(rendering ? "Rendering..." : "Render & Save"),
                ),
                SizedBox(width: 10),
                ElevatedButton.icon(onPressed: () { /* preview voice action */ showDialog(context: context, builder: (_) => PreviewVoiceDialog()); }, icon: Icon(Icons.headset), label: Text("Preview Voice")),
              ]),
              SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSelectedFilesPreview() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (characterImages.isNotEmpty) Text("Characters:"),
        Wrap(children: characterImages.map((x) => Padding(padding: EdgeInsets.all(6), child: Image.file(File(x.path), width: 80, height: 80, fit: BoxFit.cover))).toList()),
        if (characterVoiceFiles.isNotEmpty) Text("Character Voices:"),
        Column(children: characterVoiceFiles.map((f)=>ListTile(leading: Icon(Icons.audiotrack), title: Text(f.name), subtitle: Text("${(f.size/1024).toStringAsFixed(1)} KB"))).toList()),
        if (bgMusicFile != null) ListTile(leading: Icon(Icons.music_note), title: Text("BG: ${bgMusicFile!.path.split('/').last}")),
      ],
    );
  }
}

//////////////////////////////////////////////////////////////
/// Gallery Page - list videos (calls /gallery)
//////////////////////////////////////////////////////////////
class GalleryPage extends StatefulWidget {
  @override
  _GalleryPageState createState() => _GalleryPageState();
}
class _GalleryPageState extends State<GalleryPage> {
  bool loading = true;
  List<Map<String,dynamic>> videos = [];

  @override
  void initState() {
    super.initState();
    _fetchGallery();
  }

  Future<void> _fetchGallery() async {
    setState(()=>loading=true);
    try {
      final resp = await http.get(Uri.parse("$API_BASE/gallery"));
      if (resp.statusCode == 200) {
        final data = json.decode(resp.body);
        // expect list of videos with 'title' and 'file_path'
        setState(()=>videos = List<Map<String,dynamic>>.from(data));
      } else {
        setState(()=>videos = []);
      }
    } catch (e) {
      setState(()=>videos = []);
    } finally {
      setState(()=>loading=false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(child: Scaffold(
      appBar: AppBar(title: Text("Gallery")),
      body: loading ? Center(child: CircularProgressIndicator()) :
      videos.isEmpty ? Center(child: Text("No videos yet")) :
      ListView.builder(
        itemCount: videos.length,
        itemBuilder: (_,i){
          final v = videos[i];
          final title = v['title'] ?? 'Untitled';
          final fp = v['file_path'] ?? v['url'] ?? '';
          final url = fp.startsWith("http") ? fp : "$API_BASE/$fp";
          return Card(
            child: ListTile(
              leading: Icon(Icons.video_collection),
              title: Text(title),
              subtitle: Text(v['created_at'] ?? ''),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(icon: Icon(Icons.play_arrow), onPressed: () { /* open player or external url */ }),
                IconButton(icon: Icon(Icons.download), onPressed: () {
                  // open external link
                  Fluttertoast.showToast(msg: "Download URL: $url");
                }),
              ]),
            ),
          );
        }
      )
    ));
  }
}

//////////////////////////////////////////////////////////////
/// Profile Page
//////////////////////////////////////////////////////////////
class ProfilePage extends StatefulWidget {
  @override
  _ProfilePageState createState() => _ProfilePageState();
}
class _ProfilePageState extends State<ProfilePage> {
  String email = "demo@aivantu.com";
  Map<String,dynamic>? profile;
  final _nameCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }
  Future<void> _loadProfile() async {
    try {
      final resp = await http.get(Uri.parse("$API_BASE/profile/$email"));
      if (resp.statusCode==200) {
        setState(()=>profile = json.decode(resp.body));
        _nameCtrl.text = profile?['name'] ?? '';
      }
    } catch (e) {}
  }

  Future<void> _saveProfile() async {
    final body = {"email": email, "name": _nameCtrl.text};
    try {
      final resp = await http.post(Uri.parse("$API_BASE/profile"), headers: {"Content-Type":"application/json"}, body: json.encode(body));
      if (resp.statusCode==200) {
        Fluttertoast.showToast(msg: "Profile saved");
      } else {
        Fluttertoast.showToast(msg: "Save failed");
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Network error");
    }
  }

  Future<void> _pickAndUploadPhoto() async {
    final picker = ImagePicker();
    final XFile? img = await picker.pickImage(source: ImageSource.gallery, imageQuality: 85);
    if (img == null) return;
    final req = http.MultipartRequest('POST', Uri.parse("$API_BASE/upload"));
    req.fields['kind'] = 'profile';
    req.files.add(await http.MultipartFile.fromPath('file', img.path));
    final streamed = await req.send();
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode == 200) {
      Fluttertoast.showToast(msg: "Photo uploaded");
      _loadProfile();
    } else {
      Fluttertoast.showToast(msg: "Upload failed");
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(child: Scaffold(
      appBar: AppBar(title: Text("Profile")),
      body: Padding(
        padding: EdgeInsets.all(12),
        child: Column(
          children: [
            CircleAvatar(radius: 44, child: Icon(Icons.person, size:44)),
            SizedBox(height: 12),
            TextField(controller: _nameCtrl, decoration: InputDecoration(labelText: "Name")),
            SizedBox(height: 8),
            ElevatedButton.icon(onPressed: _pickAndUploadPhoto, icon: Icon(Icons.camera_alt), label: Text("Upload Photo")),
            SizedBox(height: 12),
            ElevatedButton(onPressed: _saveProfile, child: Text("Save Profile"))
          ],
        ),
      ),
    ));
  }
}

//////////////////////////////////////////////////////////////
/// Assistant Page - simple helper + preview audio
//////////////////////////////////////////////////////////////
class AssistantPage extends StatefulWidget {
  @override
  _AssistantPageState createState() => _AssistantPageState();
}
class _AssistantPageState extends State<AssistantPage> {
  final _qCtrl = TextEditingController();
  String? reply;
  String? audioUrl;
  bool loading = false;

  Future<void> _ask() async {
    if (_qCtrl.text.trim().isEmpty) return;
    setState(()=>loading=true);
    try {
      final resp = await http.post(Uri.parse("$API_BASE/assistant"), headers: {"Content-Type":"application/json"}, body: json.encode({"query":_qCtrl.text.trim(), "lang": "hi"}));
      if (resp.statusCode==200) {
        final data = json.decode(resp.body);
        setState(()=>reply = data['reply'] ?? data.toString());
        audioUrl = data['audio_url'];
      } else {
        Fluttertoast.showToast(msg: "Assistant failed");
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Network error");
    } finally { setState(()=>loading=false); }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(child: Scaffold(
      appBar: AppBar(title: Text("Assistant")),
      body: Padding(
        padding: EdgeInsets.all(12),
        child: Column(children: [
          TextField(controller: _qCtrl, decoration: InputDecoration(labelText: "Ask AI (script tips)")),
          SizedBox(height:8),
          Row(children: [
            ElevatedButton(onPressed: loading?null:_ask, child: loading?CircularProgressIndicator():Text("Get Suggestion")),
            SizedBox(width: 10),
            if (audioUrl != null) ElevatedButton(onPressed: (){ Fluttertoast.showToast(msg: "Audio URL: $audioUrl"); }, child: Text("Play Audio")),
          ]),
          SizedBox(height: 12),
          if (reply != null) Card(child: Padding(padding: EdgeInsets.all(12), child: Text(reply!))),
        ]),
      ),
    ));
  }
}

//////////////////////////////////////////////////////////////
/// Small helper dialogs
//////////////////////////////////////////////////////////////
class PreviewVoiceDialog extends StatefulWidget {
  @override
  _PreviewVoiceDialogState createState() => _PreviewVoiceDialogState();
}
class _PreviewVoiceDialogState extends State<PreviewVoiceDialog> {
  final _text = TextEditingController(text: "Hello from AiVantu preview!");
  String lang = "hi";
  bool loading = false;
  String? audioUrl;

  Future<void> _preview() async {
    setState(()=>loading=true);
    try {
      var req = http.MultipartRequest('POST', Uri.parse('$API_BASE/preview_voice'));
      req.fields['text'] = _text.text;
      req.fields['lang'] = lang;
      final streamed = await req.send();
      final respStr = await streamed.stream.bytesToString();
      if (streamed.statusCode == 200) {
        final data = json.decode(respStr);
        setState(()=>audioUrl = data['audio_url']);
        Fluttertoast.showToast(msg: "Preview ready");
      } else {
        Fluttertoast.showToast(msg: "Preview failed");
      }
    } catch (e) {
      Fluttertoast.showToast(msg: "Network error");
    } finally {
      setState(()=>loading=false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text("Preview Voice"),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: _text, decoration: InputDecoration(labelText: "Text")),
        SizedBox(height: 8),
        DropdownButton<String>(value: lang, items: ["hi","en"].map((l)=>DropdownMenuItem(value:l,child:Text(l))).toList(), onChanged: (v)=>setState(()=>lang=v!)),
        if (audioUrl != null) SelectableText("Audio: $audioUrl"),
      ]),
      actions: [
        TextButton(onPressed: ()=>Navigator.pop(context), child: Text("Close")),
        ElevatedButton(onPressed: loading?null:_preview, child: loading?CircularProgressIndicator():Text("Generate")),
      ],
    );
  }
}

class DownloadDialog extends StatelessWidget {
  final String url;
  DownloadDialog({required this.url});
  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text("Download Ready"),
      content: SelectableText(url),
      actions: [
        TextButton(onPressed: ()=>Navigator.pop(context), child: Text("Close")),
      ],
    );
  }
}
