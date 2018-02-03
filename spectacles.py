import bpy
import subprocess
import numpy as np
import os
import sys
import time

from threading import Thread
import concurrent.futures

MAX_WORKERS = 4

bl_info = {
    "name" : "Spectacles",
    "category" : "Object",
}

default_values = {
    "relative_volume" : 5,
    "begin_sound_offset" : 0,
    "end_sound_offset" : 0,
    "begin_sound_cross_duration" : 50,
    "end_sound_cross_duration" : 50,
    "begin_image" : "black.png",
    "begin_render_offset" : 0,
    "begin_image_duration" : 150,
    "begin_cross_duration" : 50,
    "end_image" : "black.png",
    "end_render_offset" : 0,
    "end_image_duration" : 200,
    "end_cross_duration" : 50,
    "end_volume_decrease_duration" : 200,
    "sound_before_start" : "no",
}

def getopt(i, opt, default = None):
    if default == None:
        return i.get(opt, default_values[opt])
    else:
        return i.get(opt, default)

def is_yes(x):
    return x != "" and x[0] in "yoYO"

envelope_path = "envelope"

def audio_env_filepath(i):
    return ".audio_" + str(i)

def video_env_filepath(x = None):
    if x != None:
        return ".video_" + str(x)
    return ".video"

def attr_filepath():
    return bpy.path.abspath("//info")

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
    sb2 = subprocess.Popen([envelope_path, str(sample_rate), str(framerate)], stdin = sb1.stdout, stdout = ofile)
    sb1.wait()
    sb2.wait()
    ofile.close()

def align_offset(fname, subs):
    data1 = np.fromfile(fname, dtype = "<i4")
    data1 = np.array(data1, dtype = float)
    data1 = data1[subs[0]:subs[1]]
    data1 -= np.mean(data1)
    data1 /= max(data1)

    data2 = np.fromfile(video_env_filepath(), dtype = "<i4")
    data2 = np.array(data2, dtype = float)
    data2 -= np.mean(data2)
    data2 /= max(data2)

    cross = np.correlate(data1, data2, mode = "full")
    opos, tol = subs[2], subs[3]
    #print(opos, tol)
    # opos-tol <= subs[0]+len(data2)-z-1 <= opos+tol
    # subs[0]+len(data2)-1-opos-tol <= z <= subs[0]+len(data2)-1+tol-opos
    bl, bh = max(0,subs[0]+len(data2)-1-opos-tol), min(subs[0]+len(data2)+tol-opos,len(cross))
    #print(bl, bh, len(cross),subs[0]+len(data2)-1-opos)
    z = np.argmax(cross[bl:bh])+bl
    return subs[0] + len(data2) - z - 1

framerate = 50
first_frame = 1

def split_seqs(sequences):
    audio = sorted([s for s in sequences if s.type == "SOUND"], key = lambda s: bpy.path.abspath(s.sound.filepath))
    video = sorted([s for s in sequences if s.type == "MOVIE"], key = lambda s: bpy.path.abspath(s.filepath))
    video_paths = {bpy.path.abspath(s.filepath) : s for s in video}
    only_audio = {}
    video_audio = {}
    i = 0
    for s in audio:
        path = bpy.path.abspath(s.sound.filepath)
        if path not in video_paths:
            only_audio[path] = (i, s)
            i += 1
        else:
            video_audio[path] = s
    return video_paths, video_audio, only_audio

def remove_all_images(context):
    img = [s for s in context.sequences if s.type == "IMAGE"]
    bpy.ops.sequencer.select_all(action='DESELECT')
    for i in img:
        i.select = True
    bpy.ops.sequencer.delete()

def getimg(context, frame_start):
    img = [s for s in context.sequences if s.type == "IMAGE"]
    for i in img:
        if i.frame_start == frame_start:
            return i
    return None

class SoundAlignCompute(bpy.types.Operator):
    """Compute Sounds Envelope"""
    bl_idname = "object.sound_align_compute"
    bl_label = "Compute Sounds Envelope"
    bl_options = {'REGISTER'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))

        only_audio = split_seqs(context.sequences)[2]

        for k in only_audio:
            compute_envelope(k, audio_env_filepath(only_audio[k][0]), framerate)
            s = only_audio[k][1]
            if "align_start" not in s:
                s["align_start"] = 0
            if "align_end" not in s:
                s["align_end"] = s.frame_duration
            if "align_near" not in s:
                s["align_near"] = 10 ** 6

        return {'FINISHED'}

class SoundAlignReference(bpy.types.Operator):
    """Compute Reference Sound Envelope"""
    bl_idname = "object.sound_align_ref"
    bl_label = "Compute Reference Sound Envelope"
    bl_options = {'REGISTER'}

    def execute(self, context):
        global framerate, first_frame
        os.chdir(bpy.path.abspath("//"))

        video_paths = split_seqs(context.sequences)[0]

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
            compute_envelope(sorted_video[i][0], video_env_filepath(i), framerate)

        f = open(video_env_filepath(), "w")
        sb = subprocess.Popen(["cat"] + [video_env_filepath(i) for i in range(len(sorted_video))], stdout = f)
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
    tol = 10 ** 6
    if "align_near" in s:
        tol = s["align_near"]
    opos = s.frame_start - first_frame
    return (low, hi, opos, tol)

class SoundAlign(bpy.types.Operator):
    """Align Sound"""
    bl_idname = "object.sound_align"
    bl_label = "Align Sound"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))

        audio = [s for s in context.selected_sequences if s.type == "SOUND"]
        audio_paths = {bpy.path.abspath(s.sound.filepath) : s for s in audio}
        only_audio = split_seqs(context.sequences)[2]

        for k in audio_paths:
            if k in only_audio:
                if only_audio[k][1].lock: continue
                off = align_offset(audio_env_filepath(only_audio[k][0]), sound_align_bounds(only_audio[k][1]))
                only_audio[k][1].frame_start = first_frame + off
        
        return {'FINISHED'}

class SoundAlignAll(bpy.types.Operator):
    """Align All Sounds"""
    bl_idname = "object.sound_align_all"
    bl_label = "Align All Sounds"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))
        only_audio = split_seqs(context.sequences)[2]

        for k in only_audio:
            if only_audio[k][1].lock: continue
            off = align_offset(audio_env_filepath(only_audio[k][0]), sound_align_bounds(only_audio[k][1]))
            only_audio[k][1].frame_start = first_frame + off
        
        return {'FINISHED'}

def parse_info():
    with open(attr_filepath(), "r") as f:
        data = f.read()
        z = data.split("\n###\n")
        d = {}
        for u in z:
            w = u.strip().split("\n")
            filename = bpy.path.abspath("//Music/" + w[0])
            r = {}
            for t in w[1:]:
                if t.strip() == "": continue
                y = t.strip().split(":", 1)
                r[y[0]] = y[1]
            d[filename] = r
        #for filename in d:
        #    print(filename + ":")
        #    print(d[filename])
        return d

def clear_anim_data(context, tp):
    fcurves = context.scene.animation_data.action.fcurves
    for i in range(len(fcurves)-1,-1,-1):
        if fcurves[i].data_path.split(".")[-1] == tp:
            fcurves.remove(fcurves[i])

def get_render_start(info, only_audio, k):
    i = info[k]
    return only_audio[k][1].frame_start + int(getopt(i, "begin_render_offset")) - int(getopt(i, "begin_image_duration"))

def get_render_end(info, only_audio, k):
    i = info[k]
    return only_audio[k][1].frame_start + only_audio[k][1].frame_duration + int(getopt(i, "end_render_offset")) + int(getopt(i, "end_image_duration"))


class SoundAjust(bpy.types.Operator):
    """Ajust Sounds"""
    bl_idname = "object.sound_ajust"
    bl_label = "Ajust Sounds"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))
        _, video_audio, only_audio = split_seqs(context.sequences)
        info = parse_info()

        clear_anim_data(context, "volume")

        for k in only_audio:
            #if only_audio[k][1].lock: continue
            if k not in info: continue
            i = info[k]
            rel_volume = float(getopt(i, "relative_volume"))
            begin_offset = int(getopt(i, "begin_sound_offset"))
            end_offset = int(getopt(i, "end_sound_offset"))
            begin_cross_duration = int(getopt(i, "begin_sound_cross_duration"))
            end_cross_duration = int(getopt(i, "end_sound_cross_duration"))
            begin = only_audio[k][1].frame_start
            end = begin + only_audio[k][1].frame_duration
            vol = 1./(1 + rel_volume)
            def set_vol_at_point(v, frame):
                for t in video_audio:
                    obj = video_audio[t]
                    obj.volume = v
                    obj.keyframe_insert(data_path = 'volume', frame = frame)
            start_vol = 1 if is_yes(getopt(i, "sound_before_start")) else 0
            set_vol_at_point(start_vol, min(get_render_start(info, only_audio, k), begin - begin_cross_duration + begin_offset))
            set_vol_at_point(start_vol, begin - begin_cross_duration + begin_offset)
            set_vol_at_point(vol, begin + begin_offset)
            set_vol_at_point(vol, end + end_offset)
            set_vol_at_point(1, end + end_cross_duration + end_offset)
            render_end = get_render_end(info, only_audio, k)
            t1 = max(end + end_cross_duration + end_offset, render_end - getopt(i, "end_volume_decrease_duration"))
            set_vol_at_point(1, t1)
            set_vol_at_point(0, render_end)
            only_audio[k][1].volume = rel_volume * vol
        
        return {'FINISHED'}

class TransitionAdd(bpy.types.Operator):
    """"""
    bl_idname = "object.transition_add"
    bl_label = "Add Transitions"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))
        info = parse_info()
        remove_all_images(context)
        _, _, only_audio = split_seqs(context.sequences)

        clear_anim_data(context, "blend_alpha")
        
        for k in info:
            i = info[k]
            if k not in only_audio: continue
            img = getopt(i, "begin_image")
            begin = get_render_start(info, only_audio, k) - 50 # -1s to avoid artifacts at the start
            end = get_render_start(info, only_audio, k) + int(getopt(i, "begin_image_duration"))
            bpy.ops.sequencer.image_strip_add(directory=bpy.path.abspath("//Images"),files=[{"name":img}],frame_start=begin)
            img = getimg(context,begin)
            img.frame_final_duration = end-begin
            img.blend_alpha = 1
            img.keyframe_insert(data_path = 'blend_alpha', frame = begin)
            img.blend_alpha = 1
            img.keyframe_insert(data_path = 'blend_alpha', frame = end - int(getopt(i, "begin_cross_duration")))
            img.blend_alpha = 0
            img.keyframe_insert(data_path = 'blend_alpha', frame = end)

            img = getopt(i, "end_image")
            begin = get_render_end(info, only_audio, k) - int(getopt(i, "end_image_duration"))
            end = get_render_end(info, only_audio, k) + 50 # +1s to avoid artifacts at the end
            bpy.ops.sequencer.image_strip_add(directory=bpy.path.abspath("//Images"),files=[{"name":img}],frame_start=begin)
            img = getimg(context,begin)
            img.frame_final_duration = end-begin
            img.blend_alpha = 0
            img.keyframe_insert(data_path = 'blend_alpha', frame = begin)
            img.blend_alpha = 1
            img.keyframe_insert(data_path = 'blend_alpha', frame = begin + int(getopt(i, "end_cross_duration")))
            img.blend_alpha = 1
            img.keyframe_insert(data_path = 'blend_alpha', frame = end)

        return {'FINISHED'}

def show_time(x):
    x = int(x)
    s = str(x % 60) + "s"
    x //= 60
    if x > 0:
        s = str(x % 60) + "m" + s
        x //= 60
        if x > 0:
            s = str(x) + "h" + s
    return s

def do_blender_call(command, filename, begin, end):
    print("Running {}".format(" ".join(command)))
    p = subprocess.Popen(command, stdout=subprocess.PIPE)
    lastpercent = 0
    tm = time.time()
    for line in p.stdout:
        if line.startswith(b"Append"):
            frame = int(line.split()[-1])
            percent = (100 * (frame - begin)) // (end - begin)
            if percent > lastpercent:
                lastpercent = percent
                Z = 5
                if percent % Z == 0:
                    t = time.time()
                    el = t - tm
                    tm = t
                    eta = el * (100 - percent) / Z
                    print("{}: {}% [{}] (elapsed: {}, ETA: {})".format(filename, percent, "=" * (percent // Z) + " " * ((100 - percent) // Z), show_time(el), show_time(eta)))
            
    p.wait()
    print("Done running {}".format(" ".join(command)))

executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
all_futures = set()

def do_wait_for_results():
    for future in concurrent.futures.as_completed(all_futures):
        future.result()
    all_futures.clear()

class ResultWaiter(Thread):
    def __init__(self):
        Thread.__init__(self)
    def run(self):
        do_wait_for_results()

def wait_for_results():
    ResultWaiter().start()

class RenderThread(Thread):
    def __init__(self, command, filename, begin, end):
        Thread.__init__(self)
        self.command = command
        self.filename = filename
        self.begin = begin
        self.end = end

    def run(self):
        do_blender_call(self.command, self.filename, self.begin, self.end)

def render_one(context, k):
    _, _, only_audio = split_seqs(context.sequences)
    info = parse_info()
    begin = get_render_start(info, only_audio, k)
    end = get_render_end(info, only_audio, k)
    filename = getopt(info[k], "filename", "render_%s.mp4" % begin)
    filename = bpy.path.abspath("//Render/" + filename)
    #bpy.data.scenes["Scene"].render.filepath = filename
    #bpy.data.scenes["Scene"].frame_start = begin
    #bpy.data.scenes["Scene"].frame_end = end
    bpath = bpy.path.abspath("//.render.blend")
    bpy.ops.wm.save_as_mainfile(filepath=bpath)
    command = ["blender", "-b", bpath, "-E", "BLENDER_RENDER", "-s", str(begin), "-e", str(end), "-o", filename, "-a"]
    #RenderThread(command, filename, begin, end).start()
    all_futures.add(executor.submit(do_blender_call, command, filename, begin, end))
    #print("Starting to render %s" % filename)
    #bpy.ops.render.render(animation=True)
    #subprocess.Popen(command)
    #print("Done")

class DoRenderOne(bpy.types.Operator):
    """"""
    bl_idname = "object.do_render_one"
    bl_label = "Render This Sequence"
    bl_options = {'REGISTER'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))
        info = parse_info()
        _, _, only_audio = split_seqs(context.selected_sequences)

        t = 0
        for k in info:
            if k not in only_audio: continue
            render_one(context, k)
        wait_for_results()
        return {'FINISHED'}

class DoRender(bpy.types.Operator):
    """"""
    bl_idname = "object.do_render"
    bl_label = "Render Everything"
    bl_options = {'REGISTER'}

    def execute(self, context):
        os.chdir(bpy.path.abspath("//"))
        info = parse_info()
        _, _, only_audio = split_seqs(context.sequences)

        t = 0
        for k in info:
            if k not in only_audio: continue
            render_one(context, k)
        wait_for_results()
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
        layout.operator(SoundAjust.bl_idname)
        layout.operator(TransitionAdd.bl_idname)
        layout.operator(DoRenderOne.bl_idname)
        layout.operator(DoRender.bl_idname)

classes = [
    SpectaclesMenu,
    SoundAlignReference,
    SoundAlignCompute,
    SoundAlign,
    SoundAlignAll,
    SoundAjust,
    TransitionAdd,
    DoRender,
    DoRenderOne,
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
