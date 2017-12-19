import bpy
import subprocess
import numpy as np
import os
import sys

bl_info = {
    "name" : "Spectacles",
    "category" : "Object",
}

#os.chdir(bpy.path.abspath("//"))

def sb_call(args):
    sb = subprocess.Popen(args, stdout=subprocess.PIPE)
    r = sb.stdout.read()
    sb.wait()
    return r.decode("utf-8")

def get_framerate(name):
    res = sb_call(["ffprobe", "-select_streams", "V", "-show_entries", "stream=r_frame_rate", "-of", "default=nk=1:nw=1", name])
    t = res.strip().split("/")
    assert (t[1] == "1")
    return int(t[0])

def get_sample_rate(name):
    return int(sb_call(["ffprobe", "-select_streams", "a", "-show_entries", "stream=sample_rate", "-of", "default=nk=1:nw=1", name]).strip())

def compute_envelope(iname, oname, framerate):
    sample_rate = get_sample_rate(iname)
    ofile = open(oname, "wb")
    sb1 = subprocess.Popen(["ffmpeg", "-i", iname, "-f", "s16le", "-ac", "1", "-c:a", "pcm_s16le", "-y", "/dev/stdout"], stdout=subprocess.PIPE)
    sb2 = subprocess.Popen(["envelope", str(sample_rate), str(framerate)], stdin = sb1.stdout, stdout = ofile)
    sb1.wait()
    sb2.wait()
    ofile.close()

def align_offset(fname, subs):
    data1 = np.fromfile(fname, dtype = "<i4")
    data1 = np.array(data1, dtype = float)
    data1 = data1[subs[0]:subs[1]]
    data1 -= np.mean(data1)
    data1 /= max(data1)

    data2 = np.fromfile("video", dtype = "<i4")
    data2 = np.array(data2, dtype = float)
    data2 -= np.mean(data2)
    data2 /= max(data2)

    cross = np.correlate(data1, data2, mode = "full")
    z = np.argmax(cross)
    return subs[0] + len(data2) - z - 1

framerate = 50
first_frame = 1

class SoundAlignCompute(bpy.types.Operator):
    """Compute Sounds Envelope"""
    bl_idname = "object.sound_align_compute"
    bl_label = "Compute Sounds Envelope"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global only_audio
        os.chdir(bpy.path.abspath("//"))
        C = bpy.context

        sequences = C.sequences
        audio = []
        video = []

        audio = [s for s in sequences if s.type == "SOUND"]
        video = [s for s in sequences if s.type == "MOVIE"]
        video_paths = {bpy.path.abspath(s.filepath) : s for s in video}
        only_audio = {}
        i = 0
        for s in audio:
            path = bpy.path.abspath(s.sound.filepath)
            if path not in video_paths:
                only_audio[path] = (i, s)
                i += 1

        for k in only_audio:
            compute_envelope(k, "audio_" + str(only_audio[k][0]), framerate)
            s = only_audio[k][1]
            if "align_start" not in s:
                s["align_start"] = 0
            if "align_end" not in s:
                s["align_end"] = s.frame_duration

        return {'FINISHED'}

class SoundAlignReference(bpy.types.Operator):
    """Compute Reference Sound Envelope"""
    bl_idname = "object.sound_align_ref"
    bl_label = "Compute Reference Sound Envelope"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global framerate, first_frame
        os.chdir(bpy.path.abspath("//"))

        video = [s for s in context.sequences if s.type == "MOVIE"]
        video_paths = {bpy.path.abspath(s.filepath) : s for s in video}

        sorted_video = sorted((k, video_paths[k]) for k in video_paths)
        for i in range(len(sorted_video) - 1):
            _, s1 = sorted_video[i]
            _, s2 = sorted_video[i+1]
            assert (s2.frame_start == s1.frame_start + s1.frame_duration)
        first_frame = sorted_video[0][1].frame_start

        framerate = get_framerate(sorted_video[0][0])
        for i in range(1, len(sorted_video)):
            assert (get_framerate(sorted_video[i][0]) == framerate)

        print("Framerate and duration ok; computing envelope...", file = sys.stderr)

        for i in range(len(sorted_video)):
            compute_envelope(sorted_video[i][0], "video_" + str(i), framerate)

        f = open("video", "w")
        sb = subprocess.Popen(["cat"] + ["video_" + str(i) for i in range(len(sorted_video))], stdout = f)
        sb.wait()
        f.close()

        print("Done", file = sys.stderr)
        
        return {'FINISHED'}

def sound_align_bounds(s):
    low = 0
    if "align_start" in s:
        low = max(low, s["align_start"])
        low = min(low, s.frame_duration)
    hi = s.frame_duration
    if "align_end" in s:
        hi = min(s["align_end"], hi)
        hi = max(hi, low)
    return (low, hi)

class SoundAlign(bpy.types.Operator):
    """Align Sound"""
    bl_idname = "object.sound_align"
    bl_label = "Align Sound"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))

        audio = [s for s in context.selected_sequences if s.type == "SOUND"]
        audio_paths = {bpy.path.abspath(s.sound.filepath) : s for s in audio}

        for k in audio_paths:
            if k in only_audio:
                if only_audio[k][1].lock: continue
                off = align_offset("audio_" + str(only_audio[k][0]), sound_align_bounds(only_audio[k][1]))
                only_audio[k][1].frame_start = first_frame + off
        
        return {'FINISHED'}

class SoundAlignAll(bpy.types.Operator):
    """Align All Sounds"""
    bl_idname = "object.sound_align_all"
    bl_label = "Align All Sounds"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))

        for k in only_audio:
            if only_audio[k][1].lock: continue
            off = align_offset("audio_" + str(only_audio[k][0]), sound_align_bounds(only_audio[k][1]))
            only_audio[k][1].frame_start = first_frame + off
        
        return {'FINISHED'}


class SpectaclesMenu(bpy.types.Menu):
    bl_idname = "SEQUENCER_MT_spectacles_menu"
    bl_label = "Spectacles"

    def draw(self, context):
        layout = self.layout

        layout.operator(SoundAlignReference.bl_idname)
        layout.operator(SoundAlignCompute.bl_idname)
        layout.operator(SoundAlign.bl_idname)
        layout.operator(SoundAlignAll.bl_idname)

classes = [
    SpectaclesMenu,
    SoundAlignReference,
    SoundAlignCompute,
    SoundAlign,
    SoundAlignAll,
]

def panel_func(self, context):
    layout = self.layout

    row = layout.row(align=True)
    row.menu(SpectaclesMenu.bl_idname, text=SpectaclesMenu.bl_label)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.SEQUENCER_MT_strip.prepend(panel_func)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.SEQUENCER_MT_strip.remove(panel_func)

if __name__ == "__main__":
    register()
