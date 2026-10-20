# Cilium 기반 홈랩 재구축

이 절차는 기존 클러스터를 중단하고 새 kubeadm 클러스터를 만드는 용도다.
실행 대상은 `inventory.ini`의 `k8s_cluster`이며, `cka_cluster`는 포함하지 않는다.
컨트롤 플레인 1대와 워커 1대 이상, Ubuntu 22.04 이상, 커널 5.10 이상,
amd64/arm64를 지원한다. 노드는 Kubernetes 전용 서버라고 가정한다.

## 파일과 기본 설정

| 파일 | 역할 |
| --- | --- |
| `vars/cilium_cluster.yml` | 버전, API 주소, Pod/Service CIDR, Cilium 옵션 |
| `preflight_cilium.yml` | OS·커널·주소·루트 파일시스템 확인, 현재 CNI 파일명 출력 |
| `reset_k8s.yml` | 명시적으로 허용했을 때만 기존 클러스터 초기화 및 노드 재부팅 |
| `bootstrap_cilium.yml` | 런타임 준비 → kubeadm init → 워커 join → Cilium → 준비 상태 확인 |

기본값은 Kubernetes **1.35.9**, Cilium **1.20.3**, Helm **3.19.0**이다.
Kubernetes 패키지는 정확한 버전으로 설치하고 hold한다. Cilium은 VXLAN과
Kubernetes IPAM을 사용한다. kubeadm이 `10.244.0.0/16`에서 노드별 Pod CIDR을
할당하고 Service CIDR은 `10.96.0.0/12`이다. Hubble Relay/UI도 설치한다.
kube-proxy는 유지한다.

API 주소는 메인 컨트롤 플레인의 `ansible_host`에서 가져온다. 노드 이름은
인벤토리 이름(`cp-01`, `worker-01`, `worker-02`)을 사용하므로 기존 Mealnote
PV의 `worker-01` nodeAffinity와 일치한다. Tailscale 등 다른 NIC가 있어도
kubelet의 node-ip는 인벤토리 LAN 주소를 사용한다.

## 초기화 전 준비

기존 클러스터의 리소스를 보존할 필요가 없고 Git에서 다시 배포할 계획이라면
아래 백업 절차 대신 `cluster_discard_existing_state=true`를 선택할 수 있다.
이 경우 etcd/리소스 백업은 필수가 아니다. Git에 없는 Secret은 다시 등록해야 하며,
DB의 기존 내용은 Argo CD가 복원하지 않는다. 이 옵션도 앱 데이터 디렉터리를 지우지는 않는다.

1. `vars/cilium_cluster.yml`을 확인한다. Pod/Service CIDR은 LAN, VPN,
   Docker, 다른 클러스터 및 라우팅되는 네트워크와 겹치면 안 된다.
   자동 검사는 두 CIDR 및 노드 LAN IP만 비교하며, 모든 라우팅 대역을 검증하지 않는다.
2. 애플리케이션 쓰기와 Argo CD 자동 동기화를 중지하고 복구할 자료를 백업한다.
   특히 `worker-01:/var/lib/mealnote`의 SQLite는 앱을 중지한 후 디렉터리 전체를
   백업하거나 SQLite의 일관된 온라인 백업 기능을 사용한다. DB 파일만 실행 중에
   복사하면 WAL에 있는 데이터가 빠질 수 있다.
3. 백업은 클러스터 외부에 저장하고 실제로 읽거나 복원할 수 있는지 확인한다.
   DB/PV 데이터, PV/PVC 정의, Secret, Argo CD 저장소 인증키, 필요한 Helm values와
   수동 리소스를 포함한다. Git에 없는 인증정보와 Vault 데이터가 있다면 함께 보관한다.
   Secret과 개인키 백업은 Git에 커밋하지 않는다.
4. 롤백용 etcd snapshot을 확보할 수 있지만, 새 클러스터에 앱을 복원할 때는
   Git 매니페스트와 데이터 백업을 사용한다. 기존 etcd를 복원하면 기존 CNI 상태도
   되살아나므로 새 Cilium 클러스터에 그대로 덮어쓰지 않는다.
5. 각 노드는 인터넷의 패키지/이미지 저장소에 접근할 수 있어야 한다.
   노드 간 Kubernetes 필수 포트, Cilium VXLAN UDP 8472, 상태 점검 TCP 4240/ICMP,
   Hubble TCP 4244 통신을 허용한다. 방화벽, 라우터, Tailscale 설정은 자동 변경하지 않는다.
   세부 요구사항은 아래 공식 문서를 따른다.

`cluster_backups_verified=true`는 사용자가 백업을 확인했다는 표시다.
플레이북이 백업을 생성하거나 복원 가능성을 자동 검증하는 것은 아니다.

## 실행

저장소 루트에서 실행한다. sudo 암호가 필요한 환경은 `-K`를 추가한다.

```bash
ansible-galaxy collection install -r requirements.yml

# 서버 변경 없이 사전 점검
ansible-playbook preflight_cilium.yml

# 문법만 확인 (서버에 접속하지 않음)
ansible-playbook --syntax-check reset_k8s.yml
ansible-playbook --syntax-check bootstrap_cilium.yml
```

기존 클러스터가 있을 때만 다음 초기화를 실행한다. 이 시점부터 서비스가 중단된다.
워크로드와 Kubernetes API 객체, 로컬 etcd가 삭제되며 노드가 순차 재부팅된다.

```bash
ansible-playbook reset_k8s.yml \
  -e cluster_reset_confirm=RESET-MAIN-CLUSTER \
  -e cluster_backups_verified=true
```

기존 클러스터 상태를 버리고 재배포한다면 위 명령 대신 다음을 실행한다.

```bash
ansible-playbook reset_k8s.yml \
  -e cluster_reset_confirm=RESET-MAIN-CLUSTER \
  -e cluster_discard_existing_state=true
```

백업 확인 변수를 상시 설정 파일에 저장하지 않는 것을 권장한다. 초기화는 워커부터
처리하고 컨트롤 플레인을 마지막에 처리한다. `/var/lib/mealnote` 등 앱 데이터
디렉터리는 삭제하지 않지만, PVC/PV와 Secret 객체는 새 클러스터에서 복원해야 한다.
OS, SSH 키, Tailscale 설정은 초기화 대상이 아니다.

```bash
# 새 클러스터 설치; reset을 자동 호출하지 않음
ansible-playbook bootstrap_cilium.yml
```

신규 서버라면 reset 없이 bootstrap만 실행한다. 메인 클러스터의 노드 준비와
설치는 `bootstrap_cilium.yml`로 실행하며 swap 비활성화도 이 과정에 포함된다.
컨테이너 런타임은 배포판의 containerd를 사용하며 설정을 기본값 + systemd cgroup으로
관리한다. 기존 containerd 설정 파일은 Ansible backup으로 보관하지만 사용자 정의
registry mirror, 인증, runtime 설정은 자동 병합하지 않는다. 그런 설정이 필요한
환경에서는 `tasks/cilium_prepare_node.yml`을 먼저 조정한다.

`--limit`, `--start-at-task`, 태그로 단계 건너뛰기는 지원하지 않는다.
전체 인벤토리를 대상으로 실행해야 모든 노드를 확인한 후 변경을 시작한다.
reset/bootstrap의 `--check`는 지원하지 않으며, `preflight_cilium.yml`을 사용한다.
fstab 이외의 zram/swap 서비스가 있다면 별도로 비활성화해야 한다.

## 선택: kube-proxy 대체

처음 구축하기 **전에** `vars/cilium_cluster.yml`을 다음과 같이 변경한다.

```yaml
cilium_kube_proxy_replacement: true
```

그러면 kubeadm의 kube-proxy 배포 단계를 생략하고 Cilium에 API 서버의 실제 LAN
주소와 포트를 전달한다. 이미 설치된 클러스터에서 이 값만 바꾸는 전환은 지원하지 않는다.
Gateway API, Ingress, LoadBalancer IPAM, L2/BGP 광고는 별도 구성이다.

## 설치 후 검증과 복구

bootstrap은 각 인벤토리 노드의 Ready 상태와 Cilium, operator, CoreDNS,
kube-proxy(사용 시), Hubble(사용 시)의 rollout을 확인한다. 준비 상태 확인만으로
노드 간 Pod 통신과 DNS, 정책 동작이 모두 검증되는 것은 아니다.

컨트롤 플레인에서 다음을 확인한다.

```bash
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes -o wide
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system get pods -o wide
```

공식 안내에 따라 Cilium CLI를 설치한 뒤 실제 통신 검사도 실행한다.
`connectivity test`는 테스트 워크로드를 생성하며 외부 통신도 검사한다.

```bash
sudo env KUBECONFIG=/etc/kubernetes/admin.conf cilium status --wait
sudo env KUBECONFIG=/etc/kubernetes/admin.conf cilium connectivity test
```

Hubble UI는 컨트롤 플레인에서 아래 명령을 실행하고 SSH 포트 포워딩으로 접근할 수 있다.

```bash
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf -n kube-system \
  port-forward svc/hubble-ui 12000:80 --address=127.0.0.1
# 내 PC의 별도 터미널에서:
ssh -L 12000:127.0.0.1:12000 ubuntu@192.168.55.10
# 브라우저: http://localhost:12000
```

통신 검증 후 스토리지/PV/PVC와 필요한 인증정보를 복원하고 Argo CD 및 앱을 배포한다.
기존 `deploy_argocd.yml`은 Argo CD 설치, `deploy-vault.yaml`의 GitHub PAT 등록,
`homelab-root` 및 `cluster-resources` Application 등록과 자동 동기화 설정까지 수행한다.
따라서 이 두 Application이 참조하는 Git 매니페스트는 다시 배포할 수 있다.
이 플레이북은 PATH에 Helm이 있어야 하므로 필요하면 기존 `helm.yml`을 먼저 실행한다.
Ansible Vault로 암호화한 파일은 기존 실행 방식에 맞춰 `--ask-vault-pass` 등을 사용한다.

```bash
ansible-playbook helm.yml
ansible-playbook deploy_argocd.yml --ask-vault-pass
```

Argo CD 자체는 DB 내용이나 Git 외부의 Secret을 복원하지 않는다. GHCR 이미지 pull
Secret은 `set_ghcr_secret.yaml`로 재등록하고, Git에서 참조하는 앱의 선행조건을 갖춘다.
이 플레이북은 `ghcr-pat-vault.yaml`의 인증정보를 사용한다.
기존 `prepare_diet_gitops.yml`은 보존된 `/var/lib/mealnote`에 PV를 다시 연결하는 데
사용할 수 있으나, 먼저 Argo CD와 저장소 접근 등 해당 플레이북의 선행조건을 갖춘다.
데이터 복구 완료 전에는 앱의 쓰기를 재개하지 않는다. 자동 앱 복구는 이 범위에 포함하지 않는다.

`/etc/kubernetes/admin.conf`는 새 인증서로 생성된다. 다른 PC나 사용자 홈의
기존 kubeconfig는 자동 교체하지 않으므로 별도로 갱신하고 권한을 `0600`으로 제한한다.
재구축 뒤 `kubectl get nodes`에 `x509: certificate signed by unknown authority`가
나오면 이전 클러스터의 kubeconfig가 남아 있는지 확인한다. 컨트롤 플레인에서
새 관리자 설정으로 접속이 되는지 먼저 확인한다.

```bash
sudo kubectl --kubeconfig=/etc/kubernetes/admin.conf get nodes
```

위 명령은 성공하지만 `ubuntu` 사용자의 기본 `kubectl`만 실패한다면,
컨트롤 플레인의 `ubuntu` 계정에서 기존 설정을 백업하고 새 설정을 복사한다.
여러 클러스터를 관리하는 kubeconfig라면 해당 클러스터 항목만 별도로 갱신한다.

```bash
mkdir -p /home/ubuntu/.kube
kubeconfig_backup=$(mktemp /home/ubuntu/.kube/config.before-rebuild.XXXXXX)
cp -p /home/ubuntu/.kube/config "$kubeconfig_backup"
sudo install -o ubuntu -g ubuntu -m 0600 \
  /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
kubectl --kubeconfig=/home/ubuntu/.kube/config get nodes
```

`KUBECONFIG` 환경변수로 다른 파일을 지정했다면 그 파일도 확인한다.
Helm은 `/usr/local/lib/ansible-helm/<version>/linux-<arch>/helm`에 설치하여 기존
`/usr/local/bin/helm`을 덮어쓰지 않는다.

같은 설정으로 bootstrap을 다시 실행하면 이미 초기화·조인된 노드는 건너뛴다.
`/etc/kubernetes/ansible-cilium/identity.json`과 비교해 Kubernetes/Cilium 버전,
노드 주소, 네트워크 및 kube-proxy 모드가 바뀌면 중단한다. 이는 업그레이드 도구가 아니다.
init/join 도중 실패하여 kubeconfig만 남은 경우에는 성공으로 간주하지 말고
`journalctl -u kubelet` 및 kubeadm 상태를 조사한다. 관리용 identity 파일을 수동으로
만들어 기존 클러스터 검사 조건을 우회하지 않는다.

reset 후에도 별도 서비스가 iptables 규칙이나 예전 CNI를 재생성한다면 해당 서비스를
먼저 정리한다. 재부팅은 임시 네트워크 상태를 정리하지만 iptables-persistent 등으로
저장한 규칙까지 제거하지 않는다. 호스트 전체 방화벽을 무조건 flush하지 않는다.

## 참고

- [Cilium kubeadm 설치 및 통신 검사](https://docs.cilium.io/en/stable/installation/k8s-install-kubeadm/)
- [Cilium Kubernetes 호환성](https://docs.cilium.io/en/stable/network/kubernetes/compatibility/)
- [Cilium 시스템·방화벽 요구사항](https://docs.cilium.io/en/stable/operations/system_requirements/)
- [Cilium kube-proxy 대체](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/)
- [kubeadm reset의 정리 범위](https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-reset/)
