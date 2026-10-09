"""Native eXpress forward action and browser policy/attachment scope, offline."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import playwright
from bridge.express.web import ExpressClient, JS_FORWARD, JS_MESSAGE_BLOB
from tests.test_express import FakeExpress, raw_event, PERSONAL, GROUP, BOSS, ME


def javascript():
    node=Path(playwright.__file__).parent/'driver/node'
    source='''(async () => {const assert=require('assert');const fs=require('fs');const scripts=JSON.parse(fs.readFileSync(0,'utf8'));
const forward=eval('('+scripts.forward+')'),blob=eval('('+scripts.blob+')');
const message={syncId:'m',groupChatId:'s',payload:{payload:{fileBlob:'blob:original'}},ruleInfo:{protected:true}};
const sourceChat={groupChatId:'s',secretHandle:'keep'},target={groupChatId:'t',name:'Target',chatType:'group_chat',connType:'rts'};
const state={messages:[message],chats:[sourceChat,target]},actions=[];
global.window={__store:{getState:()=>state,dispatch:a=>actions.push(a)},__exBlobSeq:3,__exBlobs:[
 {seq:1,size:5,url:'blob:wrong'}, {seq:2,size:5,url:'blob:preview'}, {seq:3,size:5,url:'blob:original'}]};
assert.equal(forward(['s','m','t']),true);const action=actions[0];assert.equal(action.type,'FORWARD_MESSAGES');
assert.strictEqual(action.payload.messages[0],message);assert.strictEqual(action.payload.sourceChat,sourceChat);
assert.deepEqual(action.payload.forwardDestinations,[{id:'t',chatId:'t',name:'Target',type:'group_chat',connType:'rts'}]);
for(const args of [['wrong','m','t'],['s','missing','t'],['s','m','missing']])assert.equal(forward(args),false);
message.deletedAt=1;assert.equal(forward(['s','m','t']),false);assert.equal(actions.length,1);
assert.equal(await blob([5,0,'m']),3);assert.equal(await blob([5,3,'m']),0);assert.equal(await blob([6,0,'m']),0);
assert.equal(await blob([5,0,'missing']),0);
window.__exBlobs=[];let fetched='';global.fetch=async url=>{fetched=url;return {blob:async()=>({size:5,type:'test'})}};
assert.equal(await blob([5,0,'m']),4);assert.equal(fetched,'blob:original');
delete message.payload.payload.fileBlob;assert.equal(await blob([5,0,'m']),0);
console.log('PASS: actual JavaScript forward action retains full message/source objects; missing/deleted/wrong source blocked; same-size files and previews never substitute for the original; evicted original Blob is recovered by its exact URL');
})().catch(e=>{console.error(e);process.exit(1)});'''
    subprocess.run([str(node),'-e',source],input=json.dumps(dict(forward=JS_FORWARD,blob=JS_MESSAGE_BLOB)),
                   text=True,check=True,timeout=20)


async def browser():
    parser=FakeExpress()
    message=parser.message(raw_event(10,PERSONAL,BOSS,'original'))
    forwarded=parser.message(raw_event(20,GROUP,ME,'original',forward=dict(senderHuid=BOSS)))
    client=ExpressClient('unused');calls=[];allowed=True
    async def opened(chat):calls.append(('open',chat))
    async def writable():calls.append(('writable',))
    async def loaded(chat):return []
    async def policy(msg):calls.append(('policy',msg.id));return allowed
    async def close():calls.append(('close',))
    async def sent(chat,before,timeout,**kw):
        calls.append(('sent',chat,kw));return forwarded
    async def evaluate(script,args):
        assert script==JS_FORWARD;calls.append(('dispatch',args));return True
    client._open=opened;client._writable=writable;client._loaded=loaded
    client._can_forward_open=policy;client._close=close;client._sent=sent;client._page=NS(evaluate=evaluate)
    assert await client.forward(message,GROUP) is forwarded
    assert calls[-1]==('close',) and ('dispatch',[PERSONAL,message.id,GROUP]) in calls
    assert ('sent',GROUP,dict(forwarded=True)) in calls
    allowed=False;calls.clear()
    assert await client.forward(message,GROUP) is None and calls[-1]==('close',)
    assert not any(c[0]=='dispatch' for c in calls)
    calls.clear();assert not await client.can_forward(message) and calls[-1]==('close',)
    async def broken(script,args):raise RuntimeError('web action failed')
    allowed=True;client._page.evaluate=broken;calls.clear()
    try:await client.forward(message,GROUP)
    except RuntimeError:pass
    else:raise AssertionError('failure swallowed')
    assert calls[-1]==('close',) and not client._lock.locked()
    print('PASS: native browser forwarding obeys policy before dispatch, waits for a forwarded message, closes the chat and releases lock on success/rejection/failure')


if __name__=='__main__':javascript();asyncio.run(browser())
