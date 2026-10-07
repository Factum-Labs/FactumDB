//! Desktop transport. Forensic operations stay in the Python application.
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
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
        let mut roots = vec![source.parent().unwrap().join("runtime/windows")];
        if cfg!(debug_assertions) {
            roots.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/runtime/windows"));
        }
        let bundle = roots
            .into_iter()
            .find(|p| p.join("manifest.json").is_file());
        let candidates: Vec<(String, Vec<&str>)> = if let Some(root) = &bundle {
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
        self.sequence += 1;
        let id = self.sequence.to_string();
        let request = json!({"request_id": id, "command": command, "payload": payload});
        writeln!(self.input, "{request}")
            .and_then(|_| self.input.flush())
            .map_err(|e| e.to_string())?;
        let mut line = String::new();
        if self
            .output
            .read_line(&mut line)
            .map_err(|e| e.to_string())?
            == 0
        {
            return Err("Python backend exited. Reopen FactumDB and check the configured Python installation.".into());
        }
        let response: Value =
            serde_json::from_str(&line).map_err(|e| format!("Invalid backend response: {e}"))?;
        if response["request_id"] != id {
            return Err("Backend response correlation failed".into());
        }
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
    state: tauri::State<'_, Backend>,
    command: String,
    payload: Value,
) -> Result<Value, String> {
    let backend = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut slot = backend.process.lock().map_err(|e| e.to_string())?;
        if slot.is_none() {
            let process = BackendProcess::start(backend.source, backend.workspace)?;
            *backend.child.lock().map_err(|e| e.to_string())? = Some(process.child.clone());
            *slot = Some(process);
        }
        slot.as_mut().unwrap().request(command, payload)
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
        let mut process = BackendProcess::start(source.clone(), workspace.clone()).unwrap();
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
