//! Private sidecar exchange; native approval never comes from a renderer RPC.
use serde_json::{json, Value};
use std::io::{BufRead, Write};

pub fn exchange(
    input: &mut impl Write,
    output: &mut impl BufRead,
    id: &str,
    command: &str,
    payload: Value,
    mut verify: impl FnMut() -> Result<(), String>,
) -> Result<Value, String> {
    let request = json!({"request_id": id, "command": command, "payload": payload});
    writeln!(input, "{request}")
        .and_then(|_| input.flush())
        .map_err(|e| e.to_string())?;
    let mut verified_once = false;
    loop {
        let mut line = String::new();
        if output.read_line(&mut line).map_err(|e| e.to_string())? == 0 {
            return Err("Python backend exited. Reopen FactumDB and check the configured Python installation.".into());
        }
        let response: Value =
            serde_json::from_str(&line).map_err(|e| format!("Invalid backend response: {e}"))?;
        if response["request_id"] != id {
            return Err("Backend response correlation failed".into());
        }
        if response["kind"] == "device_verification_request" {
            let nonce = response["nonce"]
                .as_str()
                .ok_or("Missing native verification nonce")?;
            if command != "auth_signup"
                || verified_once
                || response.as_object().map(|v| v.len()) != Some(3)
                || nonce.len() != 64
                || !nonce.bytes().all(|b| b.is_ascii_hexdigit())
            {
                return Err("Unexpected native verification request".into());
            }
            verified_once = true;
            let result = verify();
            let reply = json!({
                "kind": "device_verification_response", "request_id": id, "nonce": nonce,
                "result": if result.is_ok() { "verified" } else { "denied" },
                "message": result.err(),
            });
            writeln!(input, "{reply}")
                .and_then(|_| input.flush())
                .map_err(|e| e.to_string())?;
        } else if response.get("kind").is_some() {
            return Err("Unexpected private backend message".into());
        } else {
            return Ok(response);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn challenge(nonce: &str) -> Value {
        json!({"kind": "device_verification_request", "request_id": "1", "nonce": nonce})
    }

    fn stream(messages: &[Value]) -> Cursor<Vec<u8>> {
        Cursor::new(
            messages
                .iter()
                .map(|message| format!("{message}\n"))
                .collect::<String>()
                .into_bytes(),
        )
    }

    #[test]
    fn approved_exchange_echoes_private_correlation_and_returns_public_result() {
        let nonce = "ab".repeat(32);
        let mut output = stream(&[
            challenge(&nonce),
            json!({"request_id": "1", "ok": true, "result": {"user": {"username": "Test"}}}),
        ]);
        let mut input = Vec::new();
        let mut calls = 0;
        let result = exchange(
            &mut input,
            &mut output,
            "1",
            "auth_signup",
            json!({}),
            || {
                calls += 1;
                Ok(())
            },
        )
        .unwrap();
        assert_eq!(calls, 1);
        assert_eq!(result["result"]["user"]["username"], "Test");
        let messages: Vec<Value> = String::from_utf8(input)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        assert_eq!(messages.len(), 2);
        assert_eq!(
            messages[1],
            json!({"kind": "device_verification_response", "request_id": "1", "nonce": nonce, "result": "verified", "message": null})
        );
    }

    #[test]
    fn denial_is_returned_to_python_without_approval() {
        let mut output = stream(&[
            challenge(&"ab".repeat(32)),
            json!({"request_id": "1", "ok": false, "error_code": "AuthenticationError"}),
        ]);
        let mut input = Vec::new();
        let result = exchange(
            &mut input,
            &mut output,
            "1",
            "auth_signup",
            json!({}),
            || Err("Windows Hello cancelled".into()),
        )
        .unwrap();
        assert_eq!(result["ok"], false);
        let text = String::from_utf8(input).unwrap();
        let reply: Value = serde_json::from_str(text.lines().nth(1).unwrap()).unwrap();
        assert_eq!(reply["result"], "denied");
        assert_eq!(reply["message"], "Windows Hello cancelled");
    }

    #[test]
    fn malformed_or_out_of_scope_challenges_never_invoke_native_verifier() {
        let nonce = "ab".repeat(32);
        let cases = [
            ("list_cases", challenge(&nonce)),
            (
                "auth_signup",
                json!({"kind": "device_verification_request", "request_id": "2", "nonce": nonce}),
            ),
            ("auth_signup", challenge("bad-nonce")),
            ("auth_signup", challenge(&"zz".repeat(32))),
            (
                "auth_signup",
                json!({"kind": "device_verification_request", "request_id": "1", "nonce": nonce, "approved": true}),
            ),
            (
                "auth_signup",
                json!({"kind": "device_verification_response", "request_id": "1", "nonce": nonce}),
            ),
        ];
        for (command, message) in cases {
            let mut output = stream(&[message]);
            let result = exchange(
                &mut Vec::new(),
                &mut output,
                "1",
                command,
                json!({}),
                || panic!("Untrusted challenge opened native verifier"),
            );
            assert!(result.is_err());
        }
    }

    #[test]
    fn second_challenge_in_the_same_request_is_rejected() {
        let message = challenge(&"ab".repeat(32));
        let mut output = stream(&[message.clone(), message]);
        let mut calls = 0;
        let result = exchange(
            &mut Vec::new(),
            &mut output,
            "1",
            "auth_signup",
            json!({}),
            || {
                calls += 1;
                Ok(())
            },
        );
        assert!(result.is_err());
        assert_eq!(calls, 1);
    }
}
