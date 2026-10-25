import importlib.util
import socket
from pathlib import Path

module_spec = importlib.util.spec_from_file_location(
    "license_network_probe", Path(__file__).resolve().parents[1] / "scripts/check_license_network.py"
)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
probe = module.probe


def test_tcp_success_never_claims_license_or_solver_qualification():
    with socket.socket() as listening, socket.socket() as closed:
        listening.bind(("127.0.0.1", 0))
        listening.listen(4)
        closed.bind(("127.0.0.1", 0))
        port = listening.getsockname()[1]
        result = probe("127.0.0.1", port, port, (closed.getsockname()[1],), timeout=0.3)
        assert result["network_passed"] is True
        assert result["linux_license_checkout"] is False
        assert result["solver_executed"] is False


def test_unreachable_vendor_or_reachable_control_port_fails():
    with socket.socket() as listening, socket.socket() as closed:
        listening.bind(("127.0.0.1", 0))
        listening.listen(4)
        closed.bind(("127.0.0.1", 0))
        reachable, unavailable = listening.getsockname()[1], closed.getsockname()[1]
        result = probe("127.0.0.1", reachable, unavailable, (reachable,), timeout=0.3)
        assert result["tcp_reachable"]["manager"] is True
        assert result["tcp_reachable"]["vendor"] is False
        assert result["network_passed"] is False
