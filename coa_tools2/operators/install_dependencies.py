import bpy
import threading

from .. import dependency_manager


class COATOOLS2_OT_InstallPythonDependencies(bpy.types.Operator):
    bl_idname = "coa_tools2.install_python_dependencies"
    bl_label = "Install numpy / opencv"
    bl_description = "Install optional Automesh dependencies into Blender Python"
    bl_options = {"REGISTER"}

    _is_running = False

    @classmethod
    def poll(cls, context):
        return not cls._is_running

    def _progress_callback(self, progress, message):
        self.progress = max(0.0, min(100.0, float(progress)))
        self.status_message = str(message)

    def _install_worker(self):
        success, logs = dependency_manager.install_dependencies(
            progress_callback=self._progress_callback
        )
        self.success = success
        self.logs = logs
        self.done = True

    def _start(self, context):
        if COATOOLS2_OT_InstallPythonDependencies._is_running:
            self.report({"WARNING"}, "Dependency installation is already running.")
            return {"CANCELLED"}

        if context.window is None or context.screen is None:
            success, logs = dependency_manager.install_dependencies(
                progress_callback=self._progress_callback
            )
            if success:
                self.report(
                    {"INFO"},
                    "Installed numpy/opencv. Re-enable addon or restart Blender.",
                )
                return {"FINISHED"}

            failed_log = None
            for log in logs:
                if log["returncode"] != 0:
                    failed_log = log
                    break
            if failed_log is not None:
                print("COA Tools2 dependency install failed:")
                print("Command:", " ".join(failed_log["command"]))
                if failed_log["stdout"]:
                    print(failed_log["stdout"])
                if failed_log["stderr"]:
                    print(failed_log["stderr"])
            self.report(
                {"ERROR"},
                "Dependency installation failed. Existing numpy/cv2 may be incompatible. See system console.",
            )
            return {"CANCELLED"}

        COATOOLS2_OT_InstallPythonDependencies._is_running = True
        self.done = False
        self.success = False
        self.logs = []
        self.progress = 0.0
        self.status_message = "Starting dependency installation..."

        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)

        self._thread = threading.Thread(target=self._install_worker, daemon=True)
        self._thread.start()

        return {"RUNNING_MODAL"}

    def invoke(self, context, event):
        start_result = self._start(context)
        if "CANCELLED" in start_result:
            return start_result
        return context.window_manager.invoke_popup(self, width=460)

    def execute(self, context):
        return self._start(context)

    def draw(self, context):
        layout = self.layout
        layout.label(text="Installing numpy/opencv in Blender Python...")
        layout.label(text=f"Progress: {int(self.progress)}%")
        layout.label(text=self.status_message)
        if not self.done:
            layout.label(text="This window closes automatically when done.", icon="INFO")

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        wm = context.window_manager
        wm.progress_update(int(self.progress))

        # refresh UI while popup is visible
        for area in context.screen.areas:
            area.tag_redraw()

        if not self.done:
            return {"PASS_THROUGH"}

        wm.progress_end()
        wm.event_timer_remove(self._timer)
        COATOOLS2_OT_InstallPythonDependencies._is_running = False

        if self.success:
            self.report(
                {"INFO"},
                "Installed numpy/opencv. Re-enable addon or restart Blender.",
            )
            return {"FINISHED"}

        failed_log = None
        for log in self.logs:
            if log["returncode"] != 0:
                failed_log = log
                break

        if failed_log is not None:
            print("COA Tools2 dependency install failed:")
            print("Command:", " ".join(failed_log["command"]))
            if failed_log["stdout"]:
                print(failed_log["stdout"])
            if failed_log["stderr"]:
                print(failed_log["stderr"])

        self.report(
            {"ERROR"},
            "Dependency installation failed. Existing numpy/cv2 may be incompatible. See system console.",
        )
        return {"CANCELLED"}
