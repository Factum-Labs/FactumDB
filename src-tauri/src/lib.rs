//! Desktop transport. Forensic operations stay in the Python application.
mod native_verification;
#[cfg(windows)]
mod windows_hello;
use serde_json::{json, Value};
use std::{
    io::BufReader,
    path::PathBuf,
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{Arc, Mutex},
};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

struct BackendProcess {
    child: Arc<Mutex<Child>>,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    sequence: u64,
}
impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child) = self.child.lock() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}
impl BackendProcess {
    fn start(source: PathBuf, workspace: PathBuf) -> Result<Self, String> {
        let platform = if cfg!(windows) { "windows" } else { "linux" };
        let mut roots = vec![source.parent().unwrap().join("runtime").join(platform)];
        if cfg!(debug_assertions) {
            roots.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/runtime").join(platform));
        }
        let bundle = roots
            .into_iter()
            .find(|p| p.join("manifest.json").is_file());
        let candidates: Vec<(String, Vec<&str>)> = if let Some(root) = bundle.as_ref().filter(|_| cfg!(windows)) {
            vec![(
                root.join("python/python.exe")
                    .to_string_lossy()
                    .into_owned(),
                vec![],
            )]
        } else {
            match std::env::var("FACTUMDB_PYTHON") {
                Ok(path) => vec![(path, vec![])],
                Err(_) if cfg!(windows) => {
                    vec![
                        ("py".into(), vec!["-3.11"]),
                        ("py".into(), vec!["-3"]),
                        ("python".into(), vec![]),
                    ]
                }
                Err(_) => vec![("python3".into(), vec![])],
            }
        };
        if cfg!(windows) && !cfg!(debug_assertions) && bundle.is_none() {
            return Err("The Windows runtime bundle is missing. Reinstall FactumDB.".into());
        }
        let mut errors = Vec::new();
        for (program, prefix) in candidates {
            let mut command = Command::new(&program);
            command
                .args(prefix)
                .args(["-B", "-u", "-X", "utf8", "-c", "import runpy,sys; sys.path.insert(0,sys.argv.pop(1)); runpy.run_module('sidecar.desktop',run_name='__main__')"])
                .arg(&source)
                .arg("--workspace")
                .arg(&workspace)
                .current_dir(&source)
                .env("PYTHONUTF8", "1")
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::inherit());
            if cfg!(windows) {
                command.arg("--native-verification");
            }
            if let Some(root) = &bundle {
                command.env("FACTUMDB_BUNDLE_ROOT", root);
            }
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x08000000);
            }
            match command.spawn() {
                Ok(mut child) => {
                    let input = child.stdin.take().ok_or("Python stdin unavailable")?;
                    let output =
                        BufReader::new(child.stdout.take().ok_or("Python stdout unavailable")?);
                    let mut process = Self {
                        child: Arc::new(Mutex::new(child)),
                        input,
                        output,
                        sequence: 0,
                    };
                    match process.request("health".into(), json!({})) {
                        Ok(_) => return Ok(process),
                        Err(error) => errors.push(format!("{program}: {error}")),
                    }
                }
                Err(error) => errors.push(format!("{program}: {error}")),
            }
        }
        Err(format!("Cannot start the backend. Install Python 3.11+ or set FACTUMDB_PYTHON to its executable. {}", errors.join("; ")))
    }
    fn request(&mut self, command: String, payload: Value) -> Result<Value, String> {
        self.request_with_verifier(command, payload, || {
            Err("Windows Hello needs an active FactumDB window.".into())
        })
    }
    fn request_with_verifier(
        &mut self,
        command: String,
        payload: Value,
        verify: impl FnMut() -> Result<(), String>,
    ) -> Result<Value, String> {
        self.sequence += 1;
        let id = self.sequence.to_string();
        let response = native_verification::exchange(
            &mut self.input,
            &mut self.output,
            &id,
            &command,
            payload,
            verify,
        );
        let response = match response {
            Ok(response) => response,
            Err(error) => {
                // A malformed private exchange must not leave Python waiting
                // for an approval while later renderer requests enter the pipe.
                if let Ok(mut child) = self.child.lock() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                return Err(error);
            }
        };
        if response["ok"] != true {
            return Err(format!(
                "{}: {}",
                response["error_code"].as_str().unwrap_or("BackendError"),
                response["error_message"]
                    .as_str()
                    .unwrap_or("Unknown backend error")
            ));
        }
        Ok(response["result"].clone())
    }
}
#[derive(Clone)]
struct Backend {
    process: Arc<Mutex<Option<BackendProcess>>>,
    child: Arc<Mutex<Option<Arc<Mutex<Child>>>>>,
    source: PathBuf,
    workspace: PathBuf,
}

#[tauri::command]
async fn backend_request(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Backend>,
    command: String,
    payload: Value,
) -> Result<Value, String> {
    let backend = state.inner().clone();
    #[cfg(windows)]
    let window_handle = window.hwnd().map_err(|e| e.to_string())?.0 as isize;
    #[cfg(not(windows))]
    let _ = window;
    tauri::async_runtime::spawn_blocking(move || {
        let mut slot = backend.process.lock().map_err(|e| e.to_string())?;
        if slot.is_none() {
            let process = BackendProcess::start(backend.source, backend.workspace)?;
            *backend.child.lock().map_err(|e| e.to_string())? = Some(process.child.clone());
            *slot = Some(process);
        }
        slot.as_mut()
            .unwrap()
            .request_with_verifier(command, payload, || {
                #[cfg(windows)]
                {
                    windows_hello::verify(window_handle)
                }
                #[cfg(not(windows))]
                {
                    Err("Native Windows verification is unavailable on this platform.".into())
                }
            })
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn pick_evidence(app: tauri::AppHandle) -> Result<Vec<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Select evidence files")
            .blocking_pick_files()
            .unwrap_or_default()
            .into_iter()
            .map(|file| {
                file.into_path()
                    .map(|p| p.to_string_lossy().into_owned())
                    .map_err(|e| e.to_string())
            })
            .collect()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn pick_export_path(app: tauri::AppHandle, format: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let file = if format == "JSON" {
            app.dialog()
                .file()
                .set_title("Export to a new JSON file")
                .add_filter("JSON", &["json"])
                .set_file_name("case.json")
                .blocking_save_file()
        } else if format == "CSV" {
            app.dialog()
                .file()
                .set_title("Choose parent folder for CSV export")
                .blocking_pick_folder()
        } else {
            return Err("Unsupported export format".into());
        };
        file.map(|file| {
            file.into_path()
                .map(|p| p.to_string_lossy().into_owned())
                .map_err(|e| e.to_string())
        })
        .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let development = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../backend");
            let source =
                if cfg!(debug_assertions) && development.join("sidecar/desktop.py").exists() {
                    development
                } else {
                    app.path().resource_dir()?.join("backend")
                };
            app.manage(Backend {
                process: Arc::new(Mutex::new(None)),
                child: Arc::new(Mutex::new(None)),
                source,
                workspace: app.path().app_data_dir()?,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_request,
            pick_evidence,
            pick_export_path
        ])
        .build(tauri::generate_context!())
        .expect("error while building FactumDB")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                // Kill independently of the transport lock: a long stage must
                // not block the window's exit handler.
                if let Ok(child) = app.state::<Backend>().child.lock() {
                    if let Some(child) = child.as_ref() {
                        if let Ok(mut child) = child.lock() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(windows)]
    #[test]
    fn native_signup_exchange_validates_inputs_and_consumes_host_approval() {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let workspace = std::env::temp_dir().join(format!(
            "factumdb-native-auth-{}-{stamp}",
            std::process::id()
        ));
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../backend");
        let mut process = BackendProcess::start(source.clone(), workspace.clone()).unwrap();
        let signup = json!({"username": "NativeTest", "password": "Native signup password 123", "password_confirmation": "Native signup password 123"});
        let no_prompt =
            || -> Result<(), String> { panic!("Invalid inputs opened a native prompt") };
        let mut invalid = signup.clone();
        invalid["password_confirmation"] = json!("mismatch");
        assert!(process
            .request_with_verifier("auth_signup".into(), invalid, no_prompt)
            .is_err());
        let mut forged = signup.clone();
        forged["device_verified"] = json!(true);
        assert!(process
            .request_with_verifier("auth_signup".into(), forged, no_prompt)
            .is_err());
        assert!(process
            .request_with_verifier("auth_signup".into(), signup.clone(), || Err(
                "Windows Hello cancelled".into()
            ))
            .unwrap_err()
            .contains("cancelled"));
        assert_eq!(
            process.request("auth_status".into(), json!({})).unwrap()["user"],
            Value::Null
        );
        let result = process
            .request_with_verifier("auth_signup".into(), signup.clone(), || Ok(()))
            .unwrap();
        assert_eq!(result["user"]["username"], "NativeTest");
        process.request("auth_logout".into(), json!({})).unwrap();
        assert!(process
            .request_with_verifier("auth_signup".into(), signup, no_prompt)
            .unwrap_err()
            .contains("already registered"));
        assert!(process
            .request(
                "device_verification_response".into(),
                json!({"result": "verified"})
            )
            .unwrap_err()
            .contains("unknown_command"));
        drop(process);
        let mut restarted = BackendProcess::start(source, workspace.clone()).unwrap();
        assert_eq!(
            restarted.request("auth_status".into(), json!({})).unwrap()["user"],
            Value::Null
        );
        restarted
            .request(
                "auth_login".into(),
                json!({"username": "NativeTest", "password": "Native signup password 123"}),
            )
            .unwrap();
        drop(restarted);
        std::fs::remove_dir_all(workspace).unwrap();
    }
    fn seed_account(source: &std::path::Path, workspace: &std::path::Path) {
        // Provision a password account in a test workspace without opening a
        // device credential dialog in an unattended transport test.
        let bundled = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("resources/runtime/windows/python/python.exe");
        let mut command = if cfg!(windows) && bundled.is_file() {
            Command::new(bundled)
        } else if let Ok(program) = std::env::var("FACTUMDB_PYTHON") {
            Command::new(program)
        } else if cfg!(windows) {
            let mut command = Command::new("py");
            command.arg("-3.11");
            command
        } else {
            Command::new("python3")
        };
        let code = "import sys; sys.path.insert(0,sys.argv[1]); from sidecar.desktop import DesktopRuntime; from core.application.authentication import AuthenticationService; r=DesktopRuntime(sys.argv[2]); salt=bytes(range(16)); r.auth.accounts.create('Test','test',salt,AuthenticationService.digest('Transport password 123',salt),r.auth.device.identity()); r.close()";
        let result = command
            .args(["-B", "-c", code])
            .arg(source)
            .arg(workspace)
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
    }
    #[test]
    fn python_transport_persists_a_case_and_runs_the_real_pipeline() {
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let workspace =
            std::env::temp_dir().join(format!("factumdb-transport-{}-{stamp}", std::process::id()));
        std::fs::create_dir_all(&workspace).unwrap();
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../backend");
        seed_account(&source, &workspace);
        let mut process = BackendProcess::start(source.clone(), workspace.clone()).unwrap();
        assert!(process
            .request("list_cases".into(), json!({}))
            .unwrap_err()
            .contains("AuthenticationRequiredError"));
        process
            .request(
                "auth_login".into(),
                json!({"username": "Test", "password": "Transport password 123"}),
            )
            .unwrap();
        let created = process
            .request(
                "create_case".into(),
                json!({"case_name": "Transport test", "examiner": "Test"}),
            )
            .unwrap();
        let case_id = created["case_id"].as_str().unwrap();
        let index = workspace.join("binlog.index");
        std::fs::write(&index, b"binlog.000001\n").unwrap();
        process
            .request(
                "register_evidence".into(),
                json!({"case_id": case_id, "source_path": index}),
            )
            .unwrap();
        let registered = process
            .request("get_case_data".into(), json!({"case_id": case_id}))
            .unwrap();
        process.request("verify_evidence".into(), json!({"case_id": case_id, "evidence_id": registered["tables"]["evidence_files"][0]["evidence_id"]})).unwrap();
        let mut run = process
            .request("start_pipeline".into(), json!({"case_id": case_id}))
            .unwrap();
        for _ in 0..10 {
            run = process
                .request("run_next_stage".into(), json!({"run_id": run["run_id"]}))
                .unwrap();
        }
        // An index alone cannot establish evidence for analysis.
        assert_eq!(run["stages"][0]["status"], "failed", "{run}");
        assert_eq!(
            run["stages"][0]["attempts"][0]["error_code"],
            "PrerequisiteError"
        );
        let data = process
            .request("get_case_data".into(), json!({"case_id": case_id}))
            .unwrap();
        assert_eq!(
            data["tables"]["evidence_files"][0]["verification_status"],
            "verified"
        );
        assert!(process
            .request(
                "verify_evidence".into(),
                json!({"case_id": case_id, "evidence_id": "missing"})
            )
            .unwrap_err()
            .contains("NotFoundError"));
        assert_eq!(
            process.request("health".into(), json!({})).unwrap()["application_configured"],
            true
        );
        let export = workspace.join("report.json");
        assert!(process
            .request(
                "export_case".into(),
                json!({"case_id": case_id, "format": "JSON", "path": export})
            )
            .unwrap_err()
            .contains("PrerequisiteError"));
        assert!(!export.exists());
        let copy = PathBuf::from(
            data["tables"]["evidence_files"][0]["working_copy_path"]
                .as_str()
                .unwrap(),
        );
        drop(process);
        let bundled = std::env::current_exe()
            .unwrap()
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .join("backend");
        assert!(
            bundled.join("sidecar/desktop.py").exists(),
            "Python resources were not copied by the Tauri build"
        );
        let mut restarted = BackendProcess::start(bundled, workspace.clone()).unwrap();
        assert_eq!(
            restarted.request("auth_status".into(), json!({})).unwrap()["user"],
            Value::Null
        );
        restarted
            .request(
                "auth_login".into(),
                json!({"username": "Test", "password": "Transport password 123"}),
            )
            .unwrap();
        assert_eq!(
            restarted
                .request("get_case_data".into(), json!({"case_id": case_id}))
                .unwrap()["run"]["stages"][0]["status"],
            "failed"
        );
        drop(restarted);
        // Evidence working copies are deliberately read-only.
        let mut permissions = std::fs::metadata(&copy).unwrap().permissions();
        permissions.set_readonly(false);
        std::fs::set_permissions(copy, permissions).unwrap();
        std::fs::remove_dir_all(workspace).unwrap();
    }
}
