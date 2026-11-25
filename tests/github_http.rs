use forgemesh::{coordinator::Inbox, github::GitHub};
use std::{
    io::{BufRead, BufReader, Write},
    net::{TcpListener, TcpStream},
    time::Duration,
};

fn respond(mut stream: TcpStream, headers: &str, body: &str) -> String {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    let mut reader = BufReader::new(&stream);
    let mut request = String::new();
    loop {
        let mut line = String::new();
        assert_ne!(reader.read_line(&mut line).unwrap(), 0);
        request.push_str(&line);
        if line == "\r\n" {
            break;
        }
    }
    write!(stream, "HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{headers}\r\n{body}", body.len()).unwrap();
    request
}

#[test]
fn comments_follow_same_origin_pagination_without_accepting_foreign_links() {
    let server = TcpListener::bind("127.0.0.1:0").unwrap();
    let base = format!("http://{}", server.local_addr().unwrap());
    let api = GitHub::new(&base, "o/r", String::new()).unwrap();
    std::thread::scope(|scope| {
        let client = scope.spawn(|| api.comments_since(Some("2026-01-01T00:00:00Z")));
        server.set_nonblocking(true).unwrap();
        let accept = || {
            let deadline = std::time::Instant::now() + Duration::from_secs(5);
            loop {
                match server.accept() {
                    Ok((stream, _)) => return stream,
                    Err(e)
                        if e.kind() == std::io::ErrorKind::WouldBlock
                            && std::time::Instant::now() < deadline =>
                    {
                        std::thread::sleep(Duration::from_millis(10))
                    }
                    Err(e) => panic!("expected HTTP request: {e}"),
                }
            }
        };
        let first = respond(
            accept(),
            &format!("Link: <{base}/repos/o/r/issues/comments?page=2>; rel=\"next\"\r\n"),
            "[{\"id\":1}]",
        );
        assert!(first.starts_with("GET /repos/o/r/issues/comments?sort=created&direction=asc&since=2026-01-01T00:00:00Z&per_page=100 "));
        let second = respond(
            accept(),
            "Link: <http://example.invalid/steal>; rel=\"next\"\r\n",
            "[{\"id\":2}]",
        );
        assert!(second.starts_with("GET /repos/o/r/issues/comments?page=2 "));
        assert!(
            client
                .join()
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("different origin")
        );
    });
}
