#!/usr/bin/env python3
"""
GCP Compute Engine Provisioning & Gemini Chatbot Deployment Automation
Ref: compute_engine_example.ipynb
Target Secret: projects/902882112756/secrets/GEMINI_API_KEY
"""

import os
import sys
import time
import json
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "deployment.log"

PROJECT_ID = "sesac-dev-400904"
PROJECT_NUMBER = "902882112756"
ZONE = "us-central1-c"
REGION = "us-central1"
INSTANCE_NAME = f"instance-20260915-{int(time.time()) % 100000}"
SUBNET = "my-vpc"
SERVICE_ACCOUNT = f"{PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
FIREWALL_RULE = "allow-chatbot-3000"
TARGET_TAG = "chatbot-server"

def log(message: str, to_console: bool = True):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    formatted = f"[{timestamp}] {message}"
    if to_console:
        print(formatted, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")

def run_cmd(cmd, check=True, capture=True, env=None):
    log(f"RUNNING: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    
    # Ensure ADC token is injected if available
    if "CLOUDSDK_AUTH_ACCESS_TOKEN" not in run_env:
        try:
            tok = subprocess.check_output(["gcloud", "auth", "application-default", "print-access-token"], text=True).strip()
            if tok:
                run_env["CLOUDSDK_AUTH_ACCESS_TOKEN"] = tok
        except Exception:
            pass

    proc = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        env=run_env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True
    )
    output = proc.stdout if capture else ""
    if output:
        log(f"OUTPUT:\n{output.strip()}")
    if check and proc.returncode != 0:
        log(f"ERROR: Command failed with exit code {proc.returncode}")
        raise RuntimeError(f"Command failed: {proc.returncode} -> {output}")
    return proc

def main():
    global INSTANCE_NAME, ZONE
    log("================================================================================")
    log("🚀 [PHASE 1] Initializing Provisioning & Deployment Environment")
    log("================================================================================")
    log(f"Project ID: {PROJECT_ID} (Number: {PROJECT_NUMBER})")
    log(f"Zone: {ZONE}")
    log(f"Instance Name: {INSTANCE_NAME}")
    log(f"VPC Subnet: {SUBNET}")
    log(f"Service Account: {SERVICE_ACCOUNT}")

    # 1. ADC Access Token 확보
    token_proc = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"], capture_output=True, text=True)
    if token_proc.returncode == 0 and token_proc.stdout.strip():
        token = token_proc.stdout.strip()
        os.environ["CLOUDSDK_AUTH_ACCESS_TOKEN"] = token
        log("✅ Active Application Default Credentials (ADC) Token loaded successfully.")
    else:
        log("⚠️ ADC token not found. Proceeding with default credentials.")

    # 2. Secret Manager 권한 및 키 확인
    log("--------------------------------------------------------------------------------")
    log("🔑 [PHASE 2] Verifying Secret Manager GEMINI_API_KEY")
    log("--------------------------------------------------------------------------------")
    check_secret_cmd = [
        "gcloud", "secrets", "describe", "GEMINI_API_KEY",
        f"--project={PROJECT_NUMBER}"
    ]
    try:
        run_cmd(check_secret_cmd)
        log("✅ Verified Secret 'GEMINI_API_KEY' exists in Secret Manager.")
    except Exception as e:
        log(f"❌ Failed to verify Secret Manager secret: {e}")
        sys.exit(1)

    # 3. 방화벽 규칙 확인 및 생성 (Port 3000 허용)
    log("--------------------------------------------------------------------------------")
    log("🛡️ [PHASE 3] Configuring VPC Firewall for Port 3000")
    log("--------------------------------------------------------------------------------")
    fw_check = run_cmd(["gcloud", "compute", "firewall-rules", "list", f"--project={PROJECT_ID}", f"--filter=name={FIREWALL_RULE}", "--format=value(name)"], check=False)
    if FIREWALL_RULE not in fw_check.stdout:
        log(f"Firewall rule '{FIREWALL_RULE}' does not exist. Creating...")
        create_fw_cmd = [
            "gcloud", "compute", "firewall-rules", "create", FIREWALL_RULE,
            f"--project={PROJECT_ID}",
            f"--network={SUBNET}",
            "--allow=tcp:3000",
            f"--target-tags={TARGET_TAG}",
            "--description=Allow inbound traffic on port 3000 for Gemini chatbot"
        ]
        run_cmd(create_fw_cmd)
        log(f"✅ Firewall rule '{FIREWALL_RULE}' created successfully.")
    else:
        log(f"ℹ️ Firewall rule '{FIREWALL_RULE}' already exists.")

    # 4. Resource Policy (Snapshot Schedule) 확인
    disk_schedule = ""
    sched_check = run_cmd(["gcloud", "compute", "resource-policies", "list", f"--project={PROJECT_ID}", f"--regions={REGION}", "--format=value(name)"], check=False)
    if "default-schedule-1" in sched_check.stdout:
        disk_schedule = f",disk-resource-policy=projects/{PROJECT_ID}/regions/{REGION}/resourcePolicies/default-schedule-1"
        log("ℹ️ Found existing resource policy: default-schedule-1")
    else:
        log("ℹ️ default-schedule-1 not found; creating instance without disk snapshot policy.")

    # 5. Compute Engine 인스턴스 존재 여부 확인 및 생성
    log("--------------------------------------------------------------------------------")
    log("🖥️ [PHASE 4] Checking / Creating Compute Engine Instance")
    log("--------------------------------------------------------------------------------")
    inst_check = run_cmd([
        "gcloud", "compute", "instances", "list",
        f"--project={PROJECT_ID}",
        "--filter=status=RUNNING",
        "--format=value(name,zone)"
    ], check=False)
    
    current_instance = None
    if inst_check.stdout.strip():
        lines = inst_check.stdout.strip().splitlines()
        first_inst = lines[0].split()
        if len(first_inst) >= 1:
            current_instance = first_inst[0]
            if len(first_inst) >= 2:
                # zone might be a full URL or short name
                current_zone = first_inst[1].split("/")[-1]
            else:
                current_zone = ZONE
            log(f"ℹ️ Found existing RUNNING instance '{current_instance}' in zone '{current_zone}'. Reusing instance.")
            INSTANCE_NAME = current_instance
            ZONE = current_zone

    if not current_instance:
        log(f"No running instance found. Creating new Compute Engine instance '{INSTANCE_NAME}'...")
        create_vm_cmd = [
            "gcloud", "compute", "instances", "create", INSTANCE_NAME,
            f"--project={PROJECT_ID}",
            f"--zone={ZONE}",
            "--machine-type=e2-medium",
            f"--network-interface=network-tier=PREMIUM,stack-type=IPV4_ONLY,subnet={SUBNET}",
            "--metadata=enable-osconfig=TRUE",
            "--maintenance-policy=MIGRATE",
            "--provisioning-model=STANDARD",
            f"--service-account={SERVICE_ACCOUNT}",
            "--scopes=https://www.googleapis.com/auth/cloud-platform",
            f"--create-disk=auto-delete=yes,boot=yes,device-name={INSTANCE_NAME}{disk_schedule},image=projects/debian-cloud/global/images/family/debian-13,mode=rw,size=10,type=pd-balanced",
            "--no-shielded-secure-boot",
            "--shielded-vtpm",
            "--shielded-integrity-monitoring",
            f"--tags={TARGET_TAG},http-server",
            "--labels=goog-ops-agent-policy=v2-template-1-7-0,goog-ec-src=vm_add-gcloud",
            "--reservation-affinity=any"
        ]
        run_cmd(create_vm_cmd)
        log(f"✅ Compute Engine instance '{INSTANCE_NAME}' created successfully!")

    # 6. 인스턴스 외부 IP 주소 조회
    log("--------------------------------------------------------------------------------")
    log("🌐 [PHASE 5] Retrieving VM External IP Address")
    log("--------------------------------------------------------------------------------")
    ip_proc = run_cmd([
        "gcloud", "compute", "instances", "describe", INSTANCE_NAME,
        f"--project={PROJECT_ID}",
        f"--zone={ZONE}",
        "--format=value(networkInterfaces[0].accessConfigs[0].natIP)"
    ])
    external_ip = ip_proc.stdout.strip()
    log(f"🎯 Assigned External IP: {external_ip}")

    # 7. SSH 연결 대기 (인스턴스 부팅 대기 - IAP 터널링 사용)
    log("--------------------------------------------------------------------------------")
    log("⏳ [PHASE 6] Waiting for SSH daemon on VM (using IAP Tunnel)...")
    log("--------------------------------------------------------------------------------")
    ssh_ready = False
    for attempt in range(1, 15):
        log(f"SSH test attempt {attempt}/15...")
        test_ssh = run_cmd([
            "gcloud", "compute", "ssh", INSTANCE_NAME,
            f"--project={PROJECT_ID}",
            f"--zone={ZONE}",
            "--tunnel-through-iap",
            "--command=echo 'SSH_READY'",
            "--ssh-flag=-o ConnectTimeout=10",
            "--quiet"
        ], check=False)
        if "SSH_READY" in test_ssh.stdout:
            ssh_ready = True
            log("✅ SSH connection established successfully.")
            break
        time.sleep(10)

    if not ssh_ready:
        log("❌ SSH connection timed out.")
        sys.exit(1)

    # 8. 애플리케이션 파일 전송 (IAP 터널링 사용)
    log("--------------------------------------------------------------------------------")
    log("📦 [PHASE 7] Transferring Chatbot Files to VM via SCP (using IAP Tunnel)")
    log("--------------------------------------------------------------------------------")
    files_to_send = [
        str(BASE_DIR / "server.py"),
        str(BASE_DIR / "requirements.txt"),
        str(BASE_DIR / "public"),
        str(BASE_DIR / "deploy" / "setup_vm.sh")
    ]
    scp_cmd = [
        "gcloud", "compute", "scp",
        "--tunnel-through-iap",
        "--recurse"
    ] + files_to_send + [
        f"{INSTANCE_NAME}:~/",
        f"--project={PROJECT_ID}",
        f"--zone={ZONE}",
        "--quiet"
    ]
    run_cmd(scp_cmd)
    log("✅ Files transferred successfully.")

    # 9. VM 내부 프로비저닝 스크립트 실행 (IAP 터널링 사용)
    log("--------------------------------------------------------------------------------")
    log("⚙️ [PHASE 8] Executing setup_vm.sh on VM (Dependency Install & Service Start)")
    log("--------------------------------------------------------------------------------")
    exec_setup_cmd = [
        "gcloud", "compute", "ssh", INSTANCE_NAME,
        f"--project={PROJECT_ID}",
        f"--zone={ZONE}",
        "--tunnel-through-iap",
        "--command=chmod +x setup_vm.sh && ./setup_vm.sh",
        "--quiet"
    ]
    run_cmd(exec_setup_cmd)
    log("✅ VM setup script execution finished.")

    # 10. 엔드포인트 헬스체크 및 테스트 질의
    log("--------------------------------------------------------------------------------")
    log("🧪 [PHASE 9] Verification & Health Check")
    log("--------------------------------------------------------------------------------")
    time.sleep(5)
    
    # Status Check
    status_url = f"http://{external_ip}:3000/api/status"
    log(f"Querying status endpoint: {status_url}")
    status_proc = run_cmd(["curl", "-s", "--connect-timeout", "10", status_url], check=False)
    log(f"Status Response: {status_proc.stdout.strip()}")

    # Chat test query
    chat_url = f"http://{external_ip}:3000/api/chat"
    log(f"Querying chat test endpoint: {chat_url}")
    chat_payload = json.dumps({
        "input": "안녕하세요! Compute Engine에서 정상 작동 중인지 테스트 메시지입니다.",
        "model": "gemini-3.8-flash"
    })
    chat_proc = run_cmd([
        "curl", "-s", "--connect-timeout", "30",
        "-X", "POST", chat_url,
        "-H", "Content-Type: application/json",
        "-d", chat_payload
    ], check=False)
    log(f"Chat Response: {chat_proc.stdout.strip()}")

    log("================================================================================")
    log("🎉 [DEPLOYMENT SUCCESSFUL]")
    log(f"🌐 Chatbot Web UI URL: http://{external_ip}:3000")
    log(f"Instance Name: {INSTANCE_NAME}")
    log(f"Zone: {ZONE}")
    log(f"Deployment Log Path: {LOG_FILE}")
    log("================================================================================")

if __name__ == "__main__":
    main()
